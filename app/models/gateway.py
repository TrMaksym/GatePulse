from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ServiceRoute(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    fallback_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cache_ttl: Mapped[int] = mapped_column(Integer, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    retry_interval: Mapped[float] = mapped_column(Float, default=0.2)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    upstreams: Mapped[list["Upstream"]] = relationship(
        back_populates="service",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    ip_whitelist: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    ip_blacklist: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    require_jwt: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    jwt_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    path_prefix: Mapped[str | None] = mapped_column(String(200), nullable=True)
    strip_prefix: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_headers_add: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, server_default="{}")
    request_headers_remove: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="()")
    is_ai_service: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

class APIKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    client_id: Mapped[str] = mapped_column(String(100))
    tier: Mapped[str] = mapped_column(String(100), default="free")
    rate_limit: Mapped[int] = mapped_column(Integer, default=50)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Upstream(Base):
    __tablename__ = "upstreams"
    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(500))
    weight: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    service: Mapped["ServiceRoute"] = relationship(back_populates="upstreams")
