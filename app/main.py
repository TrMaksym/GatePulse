import logging
from contextlib import asynccontextmanager
import httpx
import redis
from fastapi import FastAPI
from scalar_fastapi import get_scalar_api_reference

from app.api.proxy import router as proxy_router
from app.core.config import settings
from app.core.middleware import RequestTrackingMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(
        max_keepalive_connections=settings.MAX_KEEPALIVE_CONNECTIONS,
        max_connections=settings.MAX_CONNECTIONS,
    )
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    async with httpx.AsyncClient(limits=limits, timeout=settings.TIMEOUT_SECONDS) as client:
        app.state.http_client = client
        app.state.redis = redis_client
        try:
            yield
        finally:
            await redis_client.aclose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="High-throughput API Gateway & Smart Reverse Proxy",
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(RequestTrackingMiddleware)
app.include_router(proxy_router)


@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
    }


@app.get("/scalar", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=f"{settings.PROJECT_NAME} API Reference",
    )