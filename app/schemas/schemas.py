import ipaddress
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class UpstreamBase(BaseModel):
    url: HttpUrl
    weight: int = Field(default=1, ge=1, le=100)
    is_active: bool = True


class UpstreamCreate(UpstreamBase):
    pass


class UpstreamResponse(UpstreamBase):
    id: int
    service_id: int

    model_config = ConfigDict(from_attributes=True)


class ServiceRouteBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    path_prefix: str = Field(..., min_length=1, max_length=120)
    cache_ttl: int = Field(default=60, ge=0)
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_interval: float = Field(default=0.2, ge=0.0, le=10.0)
    is_active: bool = True
    ip_whitelist: list[str] = Field(default_factory=list)
    ip_blacklist: list[str] = Field(default_factory=list)

    @classmethod
    @field_validator("ip_whitelist", "ip_blacklist")
    def validated_ip_networks(cls, v: list[str]) -> list[str]:
        for i in v:
            try:
                ipaddress.ip_network(i, strict=False)
            except ValueError:
                raise ValueError(f"Invalid IP network: {i}")
        return v


class ServiceRouteCreate(ServiceRouteBase):
    upstreams: list[UpstreamCreate] = Field(..., min_length=1)


class ServiceRouteResponse(ServiceRouteBase):
    id: int
    upstreams: list[UpstreamResponse] = []
    created_at: datetime | None = None
    path_prefix: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreate(BaseModel):
    client_id: str = Field(..., min_length=2, max_length=64)
    tier: str = Field(default="free", max_length=32)
    rate_limit: int = Field(default=50, ge=1)


class ApiKeyResponse(BaseModel):
    id: int
    client_id: str
    key_prefix: str
    tier: str
    rate_limit: int
    is_active: bool
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreatedResponse(ApiKeyResponse):
    raw_key: str