from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    PROJECT_NAME: str = "GatePulse"
    VERSION: str = "0.1.0"

    TIMEOUT_SECONDS: float = 30.0
    MAX_KEEPALIVE_CONNECTIONS: int = 50
    MAX_CONNECTIONS: int = 200

    REDIS_URL: str = "redis://localhost:6379/0"
    RATE_LIMIT_REQUESTS: int = 50
    RATE_LIMIT_INTERVAL_SECONDS: int = 60

    ROUTES: dict[str, str] = field(
        default_factory=lambda: {
            "httpbin": "https://httpbin.org",
            "dummy": "https://dummyjson.com",
        }
    )


settings = Settings()