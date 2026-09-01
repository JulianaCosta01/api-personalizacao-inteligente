import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"

sys.path.insert(0, str(SRC_DIR))

# Import após sys.path.insert (padrão do template async do Alembic). Não usado
# diretamente, mas registra as entidades em Base.metadata antes do autogenerate.
import infrastructure.database.models  # noqa: E402,F401
import infrastructure.queue.models  # noqa: E402,F401
from core.config import get_settings  # noqa: E402
from infrastructure.database.base import Base  # noqa: E402

config = context.config

settings = get_settings()

config.set_main_option(
    "sqlalchemy.url",
    settings.database_url,
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Roda as migrations sem Engine, emitindo o SQL gerado como script."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # A seção sempre existe (vem do alembic.ini); o dict vazio só satisfaz o
    # tipo exigido por async_engine_from_config.
    secao_config = config.get_section(config.config_ini_section) or {}
    connectable = async_engine_from_config(
        secao_config,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
