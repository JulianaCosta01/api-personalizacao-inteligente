from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infrastructure.database.connection import get_engine


@lru_cache
def _session_factory() -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: em contexto assíncrono, acessar um atributo expirado
    # dispara I/O implícito fora do await esperado pelo chamador.
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    """Fornece uma AsyncSession por escopo de uso, no formato esperado pelo FastAPI Depends."""
    async with _session_factory()() as session:
        yield session
