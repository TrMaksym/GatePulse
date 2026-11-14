import logging

import httpx

from app.policies.cache import get_cached_response, build_cache_key, set_cached_response
from app.policies.circuit_breaker import can_execute, record_failure, record_success
from app.policies.rate_limiter import rate_limiter
from fastapi import APIRouter, Request, status, Depends
from fastapi.responses import JSONResponse, Response
from starlette.responses import StreamingResponse

from app.core.config import settings
from app.core.constants import HOP_BY_HOP_HEADERS
from app.core.security import verify_api_key

router = APIRouter(tags=["Proxy"])

logger = logging.getLogger("gateway.proxy")

STRIPPED_HEADERS = HOP_BY_HOP_HEADERS | {"x-api-key", "host",}

@router.api_route(
    "/proxy/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    dependencies=[Depends(verify_api_key), Depends(rate_limiter)],
)
async def proxy_endpoint(service: str, path: str, request: Request):
    upstream_base_url = settings.ROUTES.get(service)

    if not upstream_base_url:
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
    target_url = f"{upstream_base_url.rstrip('/')}/{path.lstrip('/')}"
    client: httpx.AsyncClient = request.app.state.http_client

    request_id = getattr(request.state, "request_id", "unknown")

    forward_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in STRIPPED_HEADERS
    }

    forward_headers["X-Request-ID"] = request_id

    logger.info(f"[{request_id}] -> {request.method} {target_url}")

    upstream_req = client.build_request(
        method=request.method,
        url=target_url,
        headers=forward_headers,
        params=request.query_params,
        content=request.stream(),
    )

    try:
        upstream_response = await client.send(upstream_req, stream=True)
    except httpx.TimeoutException:
        await record_failure(redis, service)
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={
                "error": "Gateway Timeout",
                "message": "The upstream service took too long to respond.",
            },
        )
    except httpx.NetworkError:
        await record_failure(redis, service)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": "Bad Gateway",
                "message": "Failed to connect to the upstream service.",
            },
        )

    logger.info(f"[{request_id}] <- {upstream_response.status_code}")

    if upstream_response.status_code >= 500:
        await record_failure(redis, service)

    else:
        await record_success(redis, service)

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
                settings.cache_ttl_seconds,
            )

        clean_headers["X-Cache"] = "MISS"
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