from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, Request
from starlette.responses import StreamingResponse
from app.api.proxy import router as proxy_router
from scalar_fastapi import get_scalar_api_reference

from app.core.constants import HOP_BY_HOP_HEADERS


@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_keepalive_connections=50, max_connections=200)
    async with httpx.AsyncClient(limits=limits, timeout=30.0) as client:
        app.state.http_client = client
        yield

app = FastAPI(
    title="GatePulse",
    description="High-throughput API Gateway & Smart Reverse Proxy",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

app.include_router(proxy_router)

@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": "GatePulse",
        "version": "0.1.0",
    }

@app.get("/scalar", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title="GatePulse API Reference",
    )

@app.api_route(
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