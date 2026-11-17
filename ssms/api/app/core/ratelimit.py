"""Fixed-window rate limits: Redis in production, in-memory for development and tests."""

import time
from functools import lru_cache

from app.core.config import get_settings
from app.core.errors import AppError


class MemoryLimiter:
    def __init__(self):
        self._hits: dict[str, tuple[int, float]] = {}

    async def hit(self, key: str, window_seconds: int) -> int:
        now = time.monotonic()
        count, start = self._hits.get(key, (0, now))
        if now - start >= window_seconds:
            count, start = 0, now
        count += 1
        self._hits[key] = (count, start)
        return count

    def reset(self) -> None:
        self._hits.clear()


class RedisLimiter:
    def __init__(self, url: str):
        from redis.asyncio import Redis

        self._redis = Redis.from_url(url)

    async def hit(self, key: str, window_seconds: int) -> int:
        bucket = f"rl:{key}:{int(time.time()) // window_seconds}"
        async with self._redis.pipeline(transaction=True) as pipe:
            count, _ = await pipe.incr(bucket).expire(bucket, window_seconds).execute()
        return int(count)


@lru_cache
def get_limiter() -> MemoryLimiter | RedisLimiter:
    url = get_settings().redis_url
    return RedisLimiter(url) if url else MemoryLimiter()


async def enforce(key: str, limit: int, window_seconds: int) -> None:
    if await get_limiter().hit(key, window_seconds) > limit:
        raise AppError(
            429, "RATE_LIMITED", minutes=max(1, window_seconds // 60), headers={"Retry-After": str(window_seconds)}
        )
