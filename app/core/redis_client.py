"""
Redis client using the Upstash REST SDK (upstash-redis).

Upstash free tier exposes an HTTPS REST API — not a raw Redis TCP socket.
The upstash-redis Python SDK speaks that REST protocol natively via httpx,
so we no longer need to convert the URL to rediss://.

If credentials are missing we fall back to a no-op stub so the rest of the
app (and the webhook endpoint) continues to work without Redis.
"""

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lightweight no-op stub — used when Redis is not configured or unavailable
# ---------------------------------------------------------------------------

class _NoopRedis:
    """Drop-in stub that silently swallows every Redis call."""

    async def sismember(self, *_: Any, **__: Any) -> bool:
        return False

    async def sadd(self, *_: Any, **__: Any) -> int:
        return 0

    async def expireat(self, *_: Any, **__: Any) -> bool:
        return True

    async def get(self, *_: Any, **__: Any) -> Any:
        return None

    async def set(self, *_: Any, **__: Any) -> Any:
        return None

    async def delete(self, *_: Any, **__: Any) -> int:
        return 0

    async def hset(self, *_: Any, **__: Any) -> int:
        return 0

    async def hget(self, *_: Any, **__: Any) -> Any:
        return None

    async def hgetall(self, *_: Any, **__: Any) -> dict:
        return {}

    async def setex(self, *_: Any, **__: Any) -> Any:
        return None

    async def close(self) -> None:
        pass

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Upstash-redis async wrapper
# ---------------------------------------------------------------------------

_redis_client: Any = None


async def get_redis() -> Any:
    """Return a shared Redis client (Upstash REST SDK or no-op stub)."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    if not settings.UPSTASH_REDIS_URL or not settings.UPSTASH_REDIS_TOKEN:
        logger.warning("Redis credentials not set — using no-op stub")
        _redis_client = _NoopRedis()
        return _redis_client

    try:
        from upstash_redis.asyncio import Redis  # type: ignore
        _redis_client = Redis(
            url=settings.UPSTASH_REDIS_URL.strip(),
            token=settings.UPSTASH_REDIS_TOKEN.strip(),
        )
        # Quick ping to verify connectivity
        await _redis_client.set("__ping__", "1")
        logger.info("Upstash Redis connected via REST SDK")
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — using no-op stub", exc)
        _redis_client = _NoopRedis()

    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client and not isinstance(_redis_client, _NoopRedis):
        try:
            await _redis_client.aclose()
        except Exception:
            pass
    _redis_client = None
