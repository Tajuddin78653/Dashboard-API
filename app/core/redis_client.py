import redis.asyncio as redis
from app.config import settings

_redis_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        if settings.UPSTASH_REDIS_URL and settings.UPSTASH_REDIS_TOKEN:
            _redis_client = redis.from_url(
                settings.UPSTASH_REDIS_URL,
                password=settings.UPSTASH_REDIS_TOKEN,
                decode_responses=True,
                ssl=True,
            )
        else:
            _redis_client = redis.from_url("redis://localhost:6379", decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
