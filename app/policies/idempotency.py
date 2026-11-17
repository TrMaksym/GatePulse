import base64
import json


async def check_idempotency(redis, service: str, key: str) -> dict | str | None:
    key = f"idempotency:{service}:{key}"
    acquired = await redis.set(key, json.dumps({"status": "IN_PROGRESS"}), nx=True, ex=60)
    if acquired:
        return None
    else:
        raw = await redis.get(key)
        if not raw:
            return None
        data = json.loads(raw)
        if data.get("status") == "IN_PROGRESS":
            return "IN_PROGRESS"
        else:
            return data

async def save_idempotency(redis, service: str, key: str, status_code: int, headers: dict, body: bytes, ttl: int = 86400):
    key = f"idempotency:{service}:{key}"
    await redis.setex(key, ttl, json.dumps({"status": "SUCCESS", "status_code": status_code, "headers": headers, "body": base64.b64encode(body).decode("utf-8")}))

async def release_idempotency(redis, service: str, key: str):
    key = f"idempotency:{service}:{key}"
    await redis.delete(key)