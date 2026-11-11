import httpx
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from app.core.constants import HOP_BY_HOP_HEADERS

router = APIRouter(tags=["Proxy"])


@router.api_route(
    "/proxy/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_endpoint(path: str, request: Request):
    client: httpx.AsyncClient = request.app.state.http_client
    target_url = f"https://httpbin.org/{path}"

    forward_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }

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