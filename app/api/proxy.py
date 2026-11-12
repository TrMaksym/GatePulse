import logging

import httpx
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from app.core.config import settings
from app.core.constants import HOP_BY_HOP_HEADERS

router = APIRouter(tags=["Proxy"])

logger = logging.getLogger("gateway.proxy")

@router.api_route(
    "/proxy/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
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

    target_url = f"{upstream_base_url.rstrip('/')}/{path.lstrip('/')}"
    client: httpx.AsyncClient = request.app.state.http_client

    request_id = getattr(request.state, "request_id", "unknown")

    forward_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
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
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={
                "error": "Gateway Timeout",
                "message": "The upstream service took too long to respond.",
            },
        )
    except httpx.NetworkError:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": "Bad Gateway",
                "message": "Failed to connect to the upstream service.",
            },
        )

    logger.info(f"[{request_id}] <- {upstream_response.status_code}")

    client_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }

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