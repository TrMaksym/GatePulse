from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from app.core.config import APIKeyConfig, settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    request: Request,
    api_key: str | None = Security(api_key_header),
) -> APIKeyConfig:
    if not api_key:
        raise HTTPException(status_code=401, detail="API key is missing")

    key_info = settings.API_KEYS.get(api_key)
    if not key_info:
        raise HTTPException(status_code=403, detail="Invalid API key")

    request.state.api_key_info = key_info
    return key_info