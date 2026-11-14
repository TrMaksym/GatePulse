import time

from app.core.config import settings


async def can_execute(redis, service: str) -> bool:
    state_key = f"cb:{service}:state"
    opened_key = f"cb:{service}:opened"
    probe_lock = f"cb:{service}:probe_lock"

    state = await redis.get(state_key)
    if isinstance(state, bytes):
        state = state.decode("utf-8")

    if state is None or state == "CLOSED":
        return True
    if state == "OPEN":
        opened_at = await redis.get(opened_key)
        if isinstance(opened_at, bytes):
            opened_at = opened_at.decode("utf-8")
        if opened_at is not None and (time.time() - float(opened_at)) >= settings.cb_recovery_timeout:
            is_allowed = await redis.set(probe_lock, "1", nx=True, ex=5)
            if is_allowed:
                await redis.set(state_key, "HALF_OPEN")
                return True
            else:
                return False
    return False

async def record_success(redis, service: str) -> None:
    state_key = f"cb:{service}:state"
    failures_key = f"cb:{service}:failures"
    probe_lock = f"cb:{service}:probe_lock"
    await redis.delete(failures_key, probe_lock)
    await redis.set(state_key, "CLOSED")

async def record_failure(redis, service: str) -> None:
    state_key = f"cb:{service}:state"
    failures_key = f"cb:{service}:failures"
    opened_key = f"cb:{service}:opened"
    probe_lock = f"cb:{service}:probe_lock"
    state = await redis.get(state_key)
    if isinstance(state, bytes):
        state = state.decode("utf-8")
    failures = await redis.incr(failures_key)
    if state == "HALF_OPEN" or failures >= settings.cb_failure_threshold:
        await redis.set(state_key, "OPEN")
        await redis.set(opened_key, str(time.time()))
        await redis.delete(probe_lock)