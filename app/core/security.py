from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.gateway import APIKey
from app.repositories.gateway import get_active_api_key

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
admin_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


async def verify_api_key(
    request: Request,
    api_key: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> APIKey:
    if not api_key:
        raise HTTPException(status_code=401, detail="API key is missing")

    key_info = await get_active_api_key(db, api_key)
    if not key_info:
        raise HTTPException(status_code=403, detail="Invalid or inactive API key")

    request.state.api_key_info = key_info
    return key_info


async def verify_admin_key(
    admin_key: str | None = Security(admin_key_header),
) -> None:
    if not admin_key or admin_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing admin key")