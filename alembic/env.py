import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Load app config & models so Alembic can discover metadata
from app.config import settings

# this is the Alembic Config object
config = context.config

# Build a sync psycopg2 URL from whatever DATABASE_URL format is set
_db_url = settings.DATABASE_URL
_sync_url = (
    _db_url
    .replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    .replace("postgresql://", "postgresql+psycopg2://")
)
config.set_main_option("sqlalchemy.url", _sync_url)

# Import Base and models AFTER config is set (avoids async engine creation)
from app.database import Base  # noqa: E402
import app.models  # noqa: F401, E402

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using a synchronous engine (psycopg2 URL)."""
    from sqlalchemy import create_engine

    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)


def run_migrations_online() -> None:
    # If a connection was passed directly (e.g. from migrate.py), use it
    connectable = config.attributes.get("connection", None)
    if connectable is not None:
        do_run_migrations(connectable)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
