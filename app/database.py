from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    # statement_cache_size=0 required for Supabase transaction pooler (pgbouncer)
    connect_args={"statement_cache_size": 0},
    # Pool tuned for Supabase free tier (max 10 connections)
    # 3 persistent + 2 overflow = 5 max total — leaves headroom for other tools
    pool_size=3,
    max_overflow=2,
    pool_timeout=10,   # fail fast rather than queue forever
    pool_recycle=1800, # recycle connections every 30 min (avoids stale conn errors)
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session