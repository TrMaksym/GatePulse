import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

import httpx

logger = logging.getLogger("gateway.retry")

RETRYABLE_METHODS = {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}
RETRYABLE_STATUS_CODES = {502, 503, 504}


async def execute_with_retry(
    send_request: Callable[[], Awaitable[httpx.Response]],
    method: str,
    max_retries: int,
    retry_interval: float,
    request_id: str,
) -> tuple[httpx.Response | None, Exception | None, int]:
    allowed_retries = max_retries if method.upper() in RETRYABLE_METHODS else 0

    for attempt in range(allowed_retries + 1):
        try:
            response = await send_request()

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < allowed_retries:
                logger.warning(
                    f"[{request_id}] Retrying {response.status_code} "
                    f"(attempt {attempt + 1}/{allowed_retries + 1})"
                )
                await response.aclose()
            else:
                return response, None, attempt

        except (httpx.TimeoutException, httpx.NetworkError) as e:
            if attempt == allowed_retries:
                return None, e, attempt

            logger.warning(
                f"[{request_id}] Retrying {e} (attempt {attempt + 1}/{allowed_retries + 1})"
            )

        await asyncio.sleep(random.uniform(0, retry_interval * (2 ** attempt)))

    return None, None, allowed_retries