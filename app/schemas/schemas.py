import ipaddress
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


def _validate_ip_networks(networks: list[str] | None) -> list[str] | None:
    if networks is None:
        return None
    for net in networks:
        try:
            ipaddress.ip_network(net, strict=False)
        except ValueError:
            raise ValueError(f"Invalid IP address or CIDR network: '{net}'")
    return networks


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
    path_prefix: str | None = Field(default=None, min_length=1, max_length=120)
    strip_prefix: str | None = Field(default=None, min_length=1, max_length=120)
    cache_ttl: int = Field(default=60, ge=0)
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_interval: float = Field(default=0.2, ge=0.0, le=10.0)
    is_active: bool = True
    ip_whitelist: list[str] = Field(default_factory=list)
    ip_blacklist: list[str] = Field(default_factory=list)
    require_jwt: bool = False
    jwt_secret: str | None = Field(default=None, max_length=255)
    request_headers_add: dict[str, str] = Field(default_factory=dict)
    request_headers_remove: list[str] = Field(default_factory=list)

    @field_validator("ip_whitelist", "ip_blacklist")
    @classmethod
    def validated_ip_networks(cls, v: list[str]) -> list[str]:
        return _validate_ip_networks(v) or []


class ServiceRouteCreate(ServiceRouteBase):
    upstreams: list[UpstreamCreate] = Field(..., min_length=1)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "users-service",
                "path_prefix": "/api/v1",
                "strip_prefix": "/v1",
                "cache_ttl": 60,
                "max_retries": 2,
                "retry_interval": 0.2,
                "is_active": True,
                "ip_whitelist": [],
                "ip_blacklist": ["203.0.113.42", "198.51.100.0/24"],
                "require_jwt": True,
                "request_headers_add": {"X-Gateway": "GatePulse"},
                "request_headers_remove": ["cookie"],
                "upstreams": [
                    {
                        "url": "https://httpbin.org",
                        "weight": 1,
                        "is_active": True,
                    }
                ],
            }
        }
    )


class ServiceRouteUpdate(BaseModel):
    path_prefix: str | None = Field(default=None, min_length=1, max_length=120)
    strip_prefix: str | None = Field(default=None, min_length=1, max_length=120)
    cache_ttl: int | None = Field(default=None, ge=0)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    retry_interval: float | None = Field(default=None, ge=0.0, le=10.0)
    is_active: bool | None = None
    ip_whitelist: list[str] | None = None
    ip_blacklist: list[str] | None = None
    require_jwt: bool | None = None
    jwt_secret: str | None = Field(default=None, max_length=255)
    request_headers_add: dict[str, str] | None = None
    request_headers_remove: list[str] | None = None

    @field_validator("ip_whitelist", "ip_blacklist")
    @classmethod
    def validated_ip_networks(cls, v: list[str] | None) -> list[str] | None:
        return _validate_ip_networks(v)


class ServiceRouteResponse(ServiceRouteBase):
    id: int
    upstreams: list[UpstreamResponse] = []
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreate(BaseModel):
    client_id: str = Field(..., min_length=2, max_length=64)
    tier: str = Field(default="free", max_length=32)
    rate_limit: int = Field(default=50, ge=1)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "client_id": "mobile-app-prod",
                "tier": "pro",
                "rate_limit": 100,
            }
        }
    )


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