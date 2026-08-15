from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

import infrastructure.database.models  # noqa: F401 -- popula Base.metadata
from infrastructure.database.base import Base
from infrastructure.database.connection import get_engine
from infrastructure.database.session import get_db_session


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    gerador = get_db_session()
    session = await anext(gerador)
    try:
        yield session
    finally:
        # Os repositórios nunca commitam (Documento 4, §8 — a transação é do
        # caso de uso/request, não do repositório); o rollback aqui é o que
        # mantém cada teste isolado do próximo, sem precisar truncar tabelas.
        await session.rollback()
        await gerador.aclose()
