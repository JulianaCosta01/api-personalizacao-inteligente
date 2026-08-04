from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    # pool_pre_ping evita repassar ao chamador uma conexão que o Postgres já
    # derrubou (timeout do lado do servidor, reinício etc.).
    return create_async_engine(settings.database_url, pool_pre_ping=True)
