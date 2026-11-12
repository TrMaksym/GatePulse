import logging
import time
import uuid

import redis.asyncio as redis
from fastapi import HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger("gateway.ratelimit")


class RedisRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def __call__(self, request: Request) -> None:
        redis_client: redis.Redis = request.app.state.redis
        client_ip = request.client.host if request.client else "unknown"
        request_id = getattr(request.state, "request_id", "unknown")

        key = f"rate_limit:{client_ip}"
        now = time.time()
        window_start = now - self.window_seconds

        pipe = redis_client.pipeline(transaction=True)
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        pipe.zadd(key, {f"{now}:{uuid.uuid4()}": now})
        pipe.expire(key, self.window_seconds)
        results = await pipe.execute()

        current_requests = results[1]

        if current_requests >= self.max_requests:
            await redis_client.zremrangebyscore(key, now, now)

            oldest = await redis_client.zrange(key, 0, 0, withscores=True)
            retry_after = (
                int(self.window_seconds - (now - oldest[0][1])) + 1
                if oldest
                else self.window_seconds
            )

            logger.warning(
                f"[{request_id}] Rate limit exceeded for IP {client_ip} "
                f"({current_requests}/{self.max_requests} requests in the last {self.window_seconds} seconds)."
            )

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Too Many Requests",
                    "message": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                },
                headers={"Retry-After": str(retry_after)},
            )


rate_limiter = RedisRateLimiter(
    max_requests=settings.RATE_LIMIT_REQUESTS,
    window_seconds=settings.RATE_LIMIT_INTERVAL_SECONDS,
)