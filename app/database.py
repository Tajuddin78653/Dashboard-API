from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.config import settings

# statement_cache_size=0 required for Supabase transaction pooler (pgbouncer)
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"statement_cache_size": 0},
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
