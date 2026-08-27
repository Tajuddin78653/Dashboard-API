import redis.asyncio as redis
from app.config import settings

_redis_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        if settings.UPSTASH_REDIS_URL and settings.UPSTASH_REDIS_TOKEN:
            # Upstash free tier exposes a REST URL (https://...) but the
            # redis-py client needs a rediss:// URL.  Convert it.
            rest_url = settings.UPSTASH_REDIS_URL.strip()
            if rest_url.startswith("https://"):
                host = rest_url.replace("https://", "")
                rediss_url = f"rediss://{host}:6380"
            elif rest_url.startswith("http://"):
                host = rest_url.replace("http://", "")
                rediss_url = f"redis://{host}:6380"
            else:
                rediss_url = rest_url  # already a redis(s):// URL

            _redis_client = redis.from_url(
                rediss_url,
                password=settings.UPSTASH_REDIS_TOKEN,
                decode_responses=True,
                ssl_cert_reqs=None,  # skip cert verification for Upstash
            )
        else:
            _redis_client = redis.from_url("redis://localhost:6379", decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
