import base64
import json

def build_cache_key(service_name: str, path: str, query_params: str) -> str:
    return f"cache:{service_name}:{path}?{query_params}"

async def get_cached_response(redis, key: str) -> dict | None:
    data = await redis.get(key)
    if data is None:
        return None

    cached = json.loads(data)
    cached["body"] = base64.b64decode(cached["body"])

    return cached

async def set_cached_response(redis, key: str, body: bytes, headers:dict, ttl: int):
      payload = json.dumps({"body": base64.b64encode(body).decode("ascii"), "headers": headers})
      await redis.setex(key, ttl, payload)