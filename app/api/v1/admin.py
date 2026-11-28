from fastapi import APIRouter, status, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_admin_key
from app.policies.ai_profile import get_client_ai_usage
from app.repositories.gateway import get_service_by_name, create_service_route, create_api_key, get_all_services, \
    get_service_by_id, update_service_route
from app.schemas.schemas import ServiceRouteResponse, ServiceRouteCreate, ApiKeyCreatedResponse, ApiKeyCreate, \
    ServiceRouteUpdate

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(verify_admin_key)])


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
    return ApiKeyCreatedResponse(
        id=api_key.id,
        client_id=api_key.client_id,
        tier=api_key.tier,
        rate_limit=api_key.rate_limit,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
        key_prefix=raw_key[:10],
        raw_key=raw_key,
    )


@router.get("/services", response_model=list[ServiceRouteResponse])
async def all_services(db: AsyncSession = Depends(get_db)):
    return await get_all_services(db)


@router.patch("/services/{service_id}", response_model=ServiceRouteResponse)
async def service_by_patch(service_id: int, payload: ServiceRouteUpdate, db: AsyncSession = Depends(get_db)):
    service = await get_service_by_id(db, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    return await update_service_route(db, service, payload)

@router.get("/ai-usage/{client_id}")
async def read_client_ai_usage(
        client_id: str,
        request: Request,
        service: str | None = None
):
    redis = request.app.state.redis
    usage = await get_client_ai_usage(redis, client_id, service)
    return {
        "client_id": client_id,
        "usage": usage,
    }