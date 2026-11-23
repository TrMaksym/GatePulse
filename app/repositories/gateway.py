import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.gateway import ServiceRoute, Upstream, APIKey
from app.schemas.schemas import ServiceRouteCreate, ApiKeyCreate, ServiceRouteUpdate


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def get_service_by_name(db: AsyncSession, name: str) -> ServiceRoute | None:
    stmt = (
        select(ServiceRoute)
        .options(selectinload(ServiceRoute.upstreams))
        .where(ServiceRoute.name == name)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def get_service_by_id(db: AsyncSession, service_id: int) -> ServiceRoute | None:
    stmt = (
        select(ServiceRoute)
        .options(selectinload(ServiceRoute.upstreams))
        .where(ServiceRoute.id == service_id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def update_service_route(db: AsyncSession, service: ServiceRoute, payload: ServiceRouteUpdate):
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(service, key, value)
    await db.commit()
    return await get_service_by_id(db, service.id)

async def get_all_services(db: AsyncSession) -> list[ServiceRoute]:
    stmt = (
        select(ServiceRoute)
        .options(selectinload(ServiceRoute.upstreams))
        .order_by(ServiceRoute.id)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())

async def create_service_route(db: AsyncSession, payload: ServiceRouteCreate) -> ServiceRoute:
    service = ServiceRoute(
        **payload.model_dump(exclude={"upstreams", "path_prefix"}),
        upstreams=[
            Upstream(
                url=str(upstream.url),
                weight=upstream.weight,
                is_active=upstream.is_active,
            )
            for upstream in payload.upstreams
        ],
    )
    db.add(service)
    await db.commit()
    return await get_service_by_name(db, service.name)

async def create_api_key(db: AsyncSession, payload: ApiKeyCreate) -> tuple[APIKey, str]:
    raw_key = f"gp_{secrets.token_urlsafe(32)}"
    hashed_key = _hash_api_key(raw_key)

    api_key = APIKey(
        key=hashed_key,
        client_id=payload.client_id,
        tier=payload.tier,
        rate_limit=payload.rate_limit,
        is_active=True,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return api_key, raw_key

async def get_active_api_key(db: AsyncSession, raw_key: str) -> APIKey | None:
    hashed_key = _hash_api_key(raw_key)
    stmt = select(APIKey).where(APIKey.key == hashed_key, APIKey.is_active == True)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

