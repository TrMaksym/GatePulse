import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class APIKeyConfig:
    client_id: str
    tier: str
    rate_limit: int

def _load_api_keys() -> dict[str, APIKeyConfig]:
    raw = os.getenv("API_KEYS_JSON", "{}")
    parsed = json.loads(raw)
    return {
        api_key: APIKeyConfig(**data)
        for api_key, data in parsed.items()
    }

@dataclass(frozen=True)
class Settings:
    PROJECT_NAME: str = "GatePulse"
    VERSION: str = "0.1.0"

    TIMEOUT_SECONDS: float = 30.0
    MAX_KEEPALIVE_CONNECTIONS: int = 50
    MAX_CONNECTIONS: int = 200

    REDIS_URL: str = os.getenv("REDIS_URL")
    RATE_LIMIT_REQUESTS: int = 50
    RATE_LIMIT_INTERVAL_SECONDS: int = 60

    cache_ttl_seconds: int = 60

    API_KEYS: dict[str, APIKeyConfig] = field(default_factory=_load_api_keys)

    ROUTES: dict[str, str] = field(
        default_factory=lambda: {
            "httpbin": "https://httpbin.org",
            "dummy": "https://dummyjson.com",
        }
    )


settings = Settings()