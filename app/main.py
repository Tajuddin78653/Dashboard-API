import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

logger = logging.getLogger(__name__)
_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup — all steps non-fatal so /health always comes up ────────────
    try:
        from app.core.redis_client import get_redis
        await get_redis()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis unavailable at startup: %s", e)

    try:
        from app.database import AsyncSessionLocal
        from app.routers.strategies import seed_strategies
        async with AsyncSessionLocal() as db:
            await seed_strategies(db)
        logger.info("Strategies seeded")
    except Exception as e:
        logger.warning("Strategy seed skipped (run alembic upgrade head first): %s", e)

    try:
        from app.core.scheduler import create_scheduler
        global _scheduler
        _scheduler = create_scheduler()
        _scheduler.start()
        logger.info("Scheduler started")
    except Exception as e:
        logger.warning("Scheduler failed to start: %s", e)

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    try:
        if _scheduler:
            _scheduler.shutdown(wait=False)
    except Exception:
        pass
    try:
        from app.core.redis_client import close_redis
        await close_redis()
    except Exception:
        pass


# Resolve CORS once at import time  [deploy: 2026-08-27T14:46:35]
# If CORS_ALLOW_ALL=true or wildcard in list, open to all origins
_cors_origins = settings.CORS_ORIGINS
_allow_all = settings.CORS_ALLOW_ALL or "*" in _cors_origins

app = FastAPI(title="TradeDash API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allow_all else _cors_origins,
    allow_credentials=False if _allow_all else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routers.auth import router as auth_router
from app.routers.users import router as users_router
from app.routers.webhook import router as webhook_router
from app.routers.signals import router as signals_router
from app.routers.trades import router as trades_router
from app.routers.strategies import router as strategies_router
from app.routers.analytics import router as analytics_router
from app.routers.reports import router as reports_router
from app.routers.audit import router as audit_router
from app.routers.admin import router as admin_router

app.include_router(auth_router, prefix="/auth")
app.include_router(users_router, prefix="/users")
app.include_router(webhook_router)
app.include_router(signals_router, prefix="/signals")
app.include_router(trades_router, prefix="/trades")
app.include_router(strategies_router, prefix="/strategies")
app.include_router(analytics_router, prefix="/analytics")
app.include_router(reports_router, prefix="/reports")
app.include_router(audit_router, prefix="/audit-logs")
app.include_router(admin_router, prefix="/admin")


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok", "service": "TradeDash API"}
