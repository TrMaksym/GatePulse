from fastapi import FastAPI
from scalar_fastapi import get_scalar_api_reference


app = FastAPI(
    title="GatePulse",
    description="High-throughput API Gateway & Smart Reverse Proxy",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)

@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": "GatePulse",
        "version": "0.1.0"
    }


@app.get("/scalar", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title="GatePulse API Reference"
    )
