import httpx
from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from app.core.constants import HOP_BY_HOP_HEADERS

router = APIRouter(tags=["proxy"])

@router.api_route(
    "/proxy{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
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

    upstream_response = await client.send(upstream_req, stream=True)

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
