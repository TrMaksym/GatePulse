import hashlib
import json
from collections.abc import AsyncIterator

import logging
import httpx
from redis.asyncio import Redis


logger = logging.getLogger("gateway.ai_profile")

def is_streaming_request(body: bytes) -> bool:
    if not body:
        return False
    try:
        payload = json.loads(body)
        return isinstance(payload, dict) and payload.get("stream") is True
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False

def build_post_cache_key(service_name: str, path: str, query_params: str, body: bytes) -> str:
    try:
        parsed = json.loads(body)
        canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (json.JSONDecodeError, UnicodeDecodeError):
        canonical = body
    body_hash = hashlib.sha256(canonical).hexdigest()
    return f"cache:post:{service_name}:{path}?{query_params}:{body_hash}"

def extract_usage_from_dict(data: dict) -> dict[str, int] | None:
    usage = data.get("usage")
    if isinstance(usage, dict):
        input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (input_tokens + completion_tokens))
        if total_tokens <= 0 and input_tokens <= 0 and completion_tokens <= 0:
            return None
        return {
            "prompt_tokens": input_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
    return None

def extract_usage_from_json(body: bytes) -> dict[str, int] | None:
    if not body:
        return None
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            return extract_usage_from_dict(parsed)
        return None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

async def record_token_usage(redis: Redis, client_id: str, service_name: str, usage: dict[str, int]) -> None:
    key = f"ai_usage:{client_id}:{service_name}"
    pipe = redis.pipeline()
    pipe.hincrby(key, "prompt_tokens", usage["prompt_tokens"])
    pipe.hincrby(key, "completion_tokens", usage["completion_tokens"])
    pipe.hincrby(key, "total_tokens", usage["total_tokens"])
    pipe.hincrby(key, "requests_count", 1)
    await pipe.execute()

async def get_client_ai_usage(redis: Redis, client_id: str) -> dict[str, dict[str, int]]:
    pattern = f"ai_usage:{client_id}:*"
    stats: dict[str, dict[str, int]] = {}
    async for key in redis.scan_iter(match=pattern, count=500):
        key_str = key.decode("utf-8") if isinstance(key, bytes) else key
        service_name = key_str.split(":", 2)[2]
        raw = await redis.hgetall(key)
        stats[service_name] = {
            (k.decode("utf-8") if isinstance(k, bytes) else k): int(v)
            for k, v in raw.items()
        }
    return stats

async def sse_token_meter_stream(
    upstream_response: httpx.Response,
    redis: Redis,
    client_id: str,
    service_name: str,
    request_id: str,
) -> AsyncIterator[bytes]:
    detected_usage: dict[str, int] | None = None
    data_chunks_count = 0

    try:
        async for line in upstream_response.aiter_lines():
            if line.startswith("data:"):
                raw_data = line[5:].strip()
                if raw_data and raw_data != "[DONE]":
                    data_chunks_count += 1
                    try:
                        chunk = json.loads(raw_data)
                        if isinstance(chunk, dict):
                            usage = extract_usage_from_dict(chunk)
                            if usage:
                                detected_usage = usage
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass

            yield f"{line}\n".encode("utf-8")
    finally:
        await upstream_response.aclose()

        final_usage = detected_usage
        if final_usage is None and data_chunks_count > 0:
            final_usage = {
                "prompt_tokens": 0,
                "completion_tokens": data_chunks_count,
                "total_tokens": data_chunks_count,
            }

        if final_usage:
            await record_token_usage(redis, client_id, service_name, final_usage)
            logger.info(
                f"[{request_id}] AI Usage for {service_name}: "
                f"{final_usage['prompt_tokens']} prompt tokens, "
                f"{final_usage['completion_tokens']} completion tokens, "
                f"{final_usage['total_tokens']} total tokens"
            )