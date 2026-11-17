from app.core.config import UpstreamTarget


async def select_upstream(redis, service: str, targets: tuple[UpstreamTarget, ...]) -> str:
    if not targets:
       raise ValueError("No upstream targets available")

    if len(targets) == 1:
        return targets[0].url

    total_weight = sum(target.weight for target in targets)
    if total_weight <= 0:
        raise ValueError("Total weight of upstream targets must be greater than 0")

    key = f"lb:counter:{service}"
    counter = await redis.incr(key)
    offset = (counter - 1) % total_weight

    for target in targets:
        if target.weight <= 0:
            continue
        if offset < target.weight:
            return target.url
        else:
            offset -= target.weight
    raise ValueError("This should never happen")