from fastapi import APIRouter, status, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.repositories.gateway import get_service_by_name, create_service_route, create_api_key, get_all_services
from app.schemas.schemas import ServiceRouteResponse, ServiceRouteCreate, ApiKeyCreatedResponse, ApiKeyCreate

router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/services", response_model=ServiceRouteResponse, status_code=status.HTTP_201_CREATED)
async def register_service(
    payload: ServiceRouteCreate,
    db: AsyncSession = Depends(get_db),
):
    existing = await get_service_by_name(db, payload.name)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Service already exists",
        )
    return await create_service_route(db, payload)

@router.post("/keys", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def generate_api_key(
    payload: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
):
    api_key, raw_key = await create_api_key(db, payload)
    return ApiKeyCreatedResponse.model_validate(api_key, update={"raw_key": raw_key})

@router.get("/services", response_model=list[ServiceRouteResponse])
async def all_services(db: AsyncSession = Depends(get_db)):
    return await get_all_services(db)