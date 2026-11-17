import logging

import httpx

from app.policies.cache import get_cached_response, build_cache_key, set_cached_response, invalidate_service_cache
from app.policies.circuit_breaker import can_execute, record_failure, record_success
from app.policies.load_balancer import select_upstream
from app.policies.rate_limiter import rate_limiter
from fastapi import APIRouter, Request, status, Depends
from fastapi.responses import JSONResponse, Response
from starlette.responses import StreamingResponse

from app.core.config import settings
from app.core.constants import HOP_BY_HOP_HEADERS
from app.core.security import verify_api_key
from app.policies.retry import execute_with_retry

router = APIRouter(tags=["Proxy"])

logger = logging.getLogger("gateway.proxy")

STRIPPED_HEADERS = HOP_BY_HOP_HEADERS | {"x-api-key", "host",}

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
        content=body
    )
    return await client.send(upstream_req, stream=True)

@router.api_route(
    "/proxy/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    dependencies=[Depends(verify_api_key), Depends(rate_limiter)],
)
async def proxy_endpoint(service: str, path: str, request: Request):
    route = settings.ROUTES.get(service)

    if not route:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "Service Not Found",
                "message": f"Target service '{service}' is not configured on the gateway.",
            },
        )

    cache_key = None
    redis = request.app.state.redis
    if request.method == "GET":
        cache_key = build_cache_key(service, path, str(request.url.query))
        cached = await get_cached_response(redis, cache_key)
        if cached is not None:
            headers = dict(cached["headers"])
            headers["X-Cache"] = "HIT"

            rate_limit = getattr(request.state, "rate_limit", None)
            rate_limit_remaining = getattr(request.state, "rate_limit_remaining", None)
            if rate_limit is not None:
                headers["X-RateLimit-Limit"] = str(rate_limit)
            if rate_limit_remaining is not None:
                headers["X-RateLimit-Remaining"] = str(rate_limit_remaining)

            return Response(cached["body"], status_code=200, headers=headers)

    if not await can_execute(redis, service):
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

    request_body = await request.body()
    used_fallback = False
    selected_upstream: str | None = None

    async def attempt_primary():
        nonlocal selected_upstream
        selected_upstream = await select_upstream(redis, service, route.targets)
        return await _send_upstream_request(
            client=client,
            method=request.method,
            base_url=selected_upstream,
            path=path,
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
    if primary_error is not None or (upstream_response is not None and upstream_response.status_code >= 500):
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
                    path=path,
                    headers=forward_headers,
                    params=request.query_params,
                    body=request_body,
                    request_id=request_id,
                )
                used_fallback = True
                selected_upstream = route.fallback_url
            except httpx.TimeoutException:
                    return JSONResponse(status_code=status.HTTP_504_GATEWAY_TIMEOUT, content={
                        "error": "Gateway Timeout",
                        "message": "The upstream service timed out while processing the request.",
                })

            except httpx.NetworkError:
                    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={
                        "error": "Bad Gateway",
                    })

        elif primary_error is not None:
            if isinstance(primary_error, httpx.TimeoutException):
                return JSONResponse(status_code=status.HTTP_504_GATEWAY_TIMEOUT, content={
                    "error": "Gateway Timeout",
                    "message": "The upstream service timed out while processing the request.",
                })
            return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={
                "error": "Bad Gateway",
                "message": "The upstream service encountered an error while processing the request.",
            })
    else:
        await record_success(redis, service)


    logger.info(f"[{request_id}] <- {upstream_response.status_code}")

    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and upstream_response.status_code < 300:
        await invalidate_service_cache(redis, service)

    client_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and not key.lower().startswith("x-ratelimit-")
    }

    rate_limit = getattr(request.state, "rate_limit", None)
    rate_limit_remaining = getattr(request.state, "rate_limit_remaining", None)

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
        if rate_limit is not None:
            clean_headers["X-RateLimit-Limit"] = str(rate_limit)
        if rate_limit_remaining is not None:
            clean_headers["X-RateLimit-Remaining"] = str(rate_limit_remaining)

        return Response(
            content=body,
            status_code=upstream_response.status_code,
            headers=clean_headers,
        )

    if rate_limit is not None:

        client_headers["X-RateLimit-Limit"] = str(rate_limit)
    if used_fallback:
        client_headers["X-Fallback"] = "true"
    if selected_upstream:
        client_headers["X-Upstream-Service"] = selected_upstream
    if retries_used > 0:
        client_headers["X-Retries-Used"] = str(retries_used)
    if rate_limit_remaining is not None:
        client_headers["X-RateLimit-Remaining"] = str(rate_limit_remaining)

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