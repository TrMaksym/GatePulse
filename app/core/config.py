from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    PROJECT_NAME: str = "GatePulse"
    VERSION: str = "0.1.0"

    TIMEOUT_SECONDS: float = 30.0
    MAX_KEEPALIVE_CONNECTION: int = 50
    MAX_CONNECTIONS: int = 200

settings = Settings()

