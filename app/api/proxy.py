import base64
import logging

import httpx
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.config import UpstreamTarget, settings
from app.core.constants import HOP_BY_HOP_HEADERS
from app.core.database import get_db
from app.core.security import verify_api_key
from app.policies.ai_profile import (
    build_post_cache_key,
    is_streaming_request, sse_token_meter_stream, extract_usage_from_json, record_token_usage,
)
from app.policies.cache import (
    build_cache_key,
    get_cached_response,
    invalidate_service_cache,
    set_cached_response,
)
from app.policies.circuit_breaker import can_execute, record_failure, record_success
from app.policies.idempotency import (
    check_idempotency,
    release_idempotency,
    save_idempotency,
)
from app.policies.ip_filter import enforce_ip_policy
from app.policies.jwt_auth import verify_service_jwt
from app.policies.load_balancer import select_upstream
from app.policies.rate_limiter import rate_limiter
from app.policies.retry import execute_with_retry
from app.policies.transformations import rewrite_path, transform_headers
from app.repositories.gateway import get_service_by_name

router = APIRouter(tags=["Proxy"])

logger = logging.getLogger("gateway.proxy")

STRIPPED_HEADERS = HOP_BY_HOP_HEADERS | {"x-api-key", "host"}


def _attach_rate_limit_headers(headers: dict[str, str], request: Request) -> None:
    rate_limit = getattr(request.state, "rate_limit", None)
    rate_limit_remaining = getattr(request.state, "rate_limit_remaining", None)
    if rate_limit is not None:
        headers["X-RateLimit-Limit"] = str(rate_limit)
    if rate_limit_remaining is not None:
        headers["X-RateLimit-Remaining"] = str(rate_limit_remaining)


def _build_cached_response(cached: dict, request: Request) -> Response:
    headers = dict(cached["headers"])
    headers["X-Cache"] = "HIT"
    _attach_rate_limit_headers(headers, request)
    return Response(cached["body"], status_code=200, headers=headers)


async def _send_upstream_request(
    client: httpx.AsyncClient,
    method: str,
    base_url: str,
    path: str,
    headers: dict[str, str],
    params: dict[str, str],
    body: bytes,
    request_id: str,
) -> httpx.Response:
    target_url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    logger.info(f"[{request_id}] -> {method} {target_url}")
    upstream_req = client.build_request(
        method=method,
        url=target_url,
        headers=headers,
        params=params,
        content=body,
    )
    return await client.send(upstream_req, stream=True)


@router.api_route(
    "/proxy/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    dependencies=[Depends(verify_api_key), Depends(rate_limiter)],
)
async def proxy_endpoint(
    service: str,
    path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    route = await get_service_by_name(db, service)

    if not route or not route.is_active:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "Service Not Found",
                "message": f"Target service '{service}' is not configured on the gateway.",
            },
        )

    enforce_ip_policy(request, route.ip_whitelist or [], route.ip_blacklist or [])
    jwt_payload = verify_service_jwt(
        request,
        bool(route.require_jwt),
        str(route.jwt_secret) if route.jwt_secret else None,
    )

    is_ai_service = bool(route.is_ai_service)
    api_client_id = str(getattr(request.state, "client_id", "unknown"))
    request_body: bytes | None = None
    is_ai_streaming = False

    cache_key = None
    redis = request.app.state.redis
    if request.method == "GET":
        cache_key = build_cache_key(service, path, str(request.url.query))
        cached = await get_cached_response(redis, cache_key)
        if cached is not None:
            return _build_cached_response(cached, request)

    if is_ai_service and request.method == "POST":
        request_body = await request.body()
        is_ai_streaming = is_streaming_request(request_body)
        if not is_ai_streaming:
            cache_key = build_post_cache_key(
                service, path, str(request.url.query), request_body
            )
            cached = await get_cached_response(redis, cache_key)
            if cached is not None:
                return _build_cached_response(cached, request)

    idempotency_key = request.headers.get("X-Idempotency-Key")
    use_idempotency = bool(
        idempotency_key and request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
    )
    if use_idempotency:
        cached_item = await check_idempotency(redis, service, idempotency_key)
        if cached_item == "IN_PROGRESS":
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"detail": "Request already in progress"},
            )
        if isinstance(cached_item, dict):
            body = base64.b64decode(cached_item["body"])
            headers = dict(cached_item["headers"])
            headers["X-Idempotency-Key"] = idempotency_key
            headers["X-Idempotency-Hit"] = "true"
            _attach_rate_limit_headers(headers, request)
            return Response(
                content=body,
                status_code=cached_item["status_code"],
                headers=headers,
            )

    if not await can_execute(redis, service):
        if use_idempotency:
            await release_idempotency(redis, service, idempotency_key)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "Service Unavailable",
                "message": f"The target service '{service}' is currently unavailable.",
            },
        )

    client: httpx.AsyncClient = request.app.state.http_client
    request_id = getattr(request.state, "request_id", "unknown")

    forward_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in STRIPPED_HEADERS
    }
    forward_headers["X-Request-ID"] = request_id

    if request_body is None:
        request_body = await request.body()

    used_fallback = False
    selected_upstream: str | None = None

    active_upstreams = tuple(
        UpstreamTarget(url=u.url, weight=u.weight)
        for u in route.upstreams
        if u.is_active
    )
    if not active_upstreams:
        if use_idempotency:
            await release_idempotency(redis, service, idempotency_key)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "Service Unavailable",
                "message": f"No active upstream services found for '{service}'.",
            },
        )

    target_path = rewrite_path(
        path,
        str(route.strip_prefix) if route.strip_prefix else None,
        str(route.path_prefix) if route.path_prefix else None,
    )
    forward_headers = transform_headers(
        forward_headers,
        list(route.request_headers_remove) if route.request_headers_remove else None,
        dict(route.request_headers_add) if route.request_headers_add else None,
        jwt_payload,
    )

    async def attempt_primary():
        nonlocal selected_upstream
        selected_upstream = await select_upstream(redis, service, active_upstreams)
        return await _send_upstream_request(
            client=client,
            method=request.method,
            base_url=selected_upstream,
            path=target_path,
            headers=forward_headers,
            params=request.query_params,
            body=request_body,
            request_id=request_id,
        )

    upstream_response, primary_error, retries_used = await execute_with_retry(
        send_request=attempt_primary,
        method=request.method,
        max_retries=route.max_retries,
        retry_interval=route.retry_interval,
        request_id=request_id,
    )

    if primary_error is not None or (
        upstream_response is not None and upstream_response.status_code >= 500
    ):
        await record_failure(redis, service)

        if route.fallback_url:
            if upstream_response is not None:
                await upstream_response.aclose()

            logger.warning(f"[{request_id}] Fallback to {route.fallback_url}")
            try:
                upstream_response = await _send_upstream_request(
                    client=client,
                    method=request.method,
                    base_url=route.fallback_url,
                    path=target_path,
                    headers=forward_headers,
                    params=request.query_params,
                    body=request_body,
                    request_id=request_id,
                )
                used_fallback = True
                selected_upstream = route.fallback_url
            except httpx.TimeoutException:
                if use_idempotency:
                    await release_idempotency(redis, service, idempotency_key)
                return JSONResponse(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    content={
                        "error": "Gateway Timeout",
                        "message": "The upstream service timed out while processing the request.",
                    },
                )
            except httpx.NetworkError:
                if use_idempotency:
                    await release_idempotency(redis, service, idempotency_key)
                return JSONResponse(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    content={"error": "Bad Gateway"},
                )

        elif primary_error is not None:
            if use_idempotency:
                await release_idempotency(redis, service, idempotency_key)
            if isinstance(primary_error, httpx.TimeoutException):
                return JSONResponse(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    content={
                        "error": "Gateway Timeout",
                        "message": "The upstream service timed out while processing the request.",
                    },
                )
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={
                    "error": "Bad Gateway",
                    "message": "The upstream service encountered an error while processing the request.",
                },
            )
    else:
        await record_success(redis, service)

    logger.info(f"[{request_id}] <- {upstream_response.status_code}")

    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and upstream_response.status_code < 300
        and not (is_ai_service and request.method == "POST")
    ):
        await invalidate_service_cache(redis, service)

    client_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
        and not key.lower().startswith("x-ratelimit-")
    }

    if request.method == "GET":
        body = await upstream_response.aread()
        await upstream_response.aclose()

        clean_headers = {
            k: v for k, v in client_headers.items() if k.lower() != "content-encoding"
        }

        if upstream_response.status_code == 200 and cache_key:
            await set_cached_response(
                redis,
                cache_key,
                body,
                clean_headers,
                route.cache_ttl,
            )

        clean_headers["X-Cache"] = "MISS"
        if used_fallback:
            clean_headers["X-Fallback"] = "true"
        if retries_used > 0:
            clean_headers["X-Retries-Used"] = str(retries_used)
        if selected_upstream:
            clean_headers["X-Upstream-Service"] = selected_upstream
        _attach_rate_limit_headers(clean_headers, request)

        return Response(
            content=body,
            status_code=upstream_response.status_code,
            headers=clean_headers,
        )

    _attach_rate_limit_headers(client_headers, request)
    if used_fallback:
        client_headers["X-Fallback"] = "true"
    if selected_upstream:
        client_headers["X-Upstream-Service"] = selected_upstream
    if retries_used > 0:
        client_headers["X-Retries-Used"] = str(retries_used)

    if use_idempotency:
        body = await upstream_response.aread()
        await upstream_response.aclose()

        clean_headers = {
            k: v for k, v in client_headers.items() if k.lower() != "content-encoding"
        }
        clean_headers["X-Idempotency-Key"] = idempotency_key
        clean_headers["X-Idempotency-Hit"] = "false"
        if upstream_response.status_code >= 500:
            await release_idempotency(redis, service, idempotency_key)
        else:
            await save_idempotency(
                redis,
                service,
                idempotency_key,
                upstream_response.status_code,
                clean_headers,
                body,
            )

        return Response(
            content=body,
            status_code=upstream_response.status_code,
            headers=clean_headers,
        )

    if is_ai_service:
        is_sse = is_ai_streaming or upstream_response.headers.get("Content-Type", "").startswith("text/event-stream")
        if is_sse:
            return StreamingResponse(
                content=sse_token_meter_stream(
                    upstream_response,
                    redis,
                    api_client_id,
                    service,
                    request_id
                ),
                status_code=upstream_response.status_code,
                headers=client_headers,
            )
        else:
            body = await upstream_response.aread()
            await upstream_response.aclose()
            usage = extract_usage_from_json(body)
            if usage:
                await record_token_usage(redis, api_client_id, service, usage)
            clean_headers = {k: v for k, v in client_headers.items() if k.lower() != "content-encoding"}
            if upstream_response.status_code == 200 and cache_key:
                await set_cached_response(
                    redis,
                    cache_key,
                    body,
                    clean_headers,
                    route.cache_ttl,
                )
            clean_headers["X-Cache"] = "MISS"
            return Response(
                content=body,
                status_code=upstream_response.status_code,
                headers=clean_headers,
            )

    async def body_stream():
        try:
            async for chunk in upstream_response.aiter_raw():
                yield chunk
        finally:
            await upstream_response.aclose()

    return StreamingResponse(
        content=body_stream(),
        status_code=upstream_response.status_code,
        headers=client_headers,
    )