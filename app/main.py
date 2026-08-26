from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.redis_client import get_redis, close_redis
from app.core.scheduler import create_scheduler
from app.routers.auth import router as auth_router
from app.routers.users import router as users_router
from app.routers.webhook import router as webhook_router
from app.routers.signals import router as signals_router
from app.routers.trades import router as trades_router
from app.routers.strategies import router as strategies_router, seed_strategies
from app.routers.analytics import router as analytics_router
from app.routers.reports import router as reports_router
from app.routers.audit import router as audit_router
from app.routers.admin import router as admin_router
from app.database import AsyncSessionLocal

_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await get_redis()
    async with AsyncSessionLocal() as db:
        await seed_strategies(db)
    global _scheduler
    _scheduler = create_scheduler()
    _scheduler.start()
    yield
    # Shutdown
    if _scheduler:
        _scheduler.shutdown(wait=False)
    await close_redis()


app = FastAPI(title="TradeDash API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/health")
async def health():
    return {"status": "ok", "service": "TradeDash API"}
