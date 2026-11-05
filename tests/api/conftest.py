import os
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import infrastructure.database.models  # noqa: F401 -- popula Base.metadata
import infrastructure.queue.models  # noqa: F401 -- popula Base.metadata
from infrastructure.database.base import Base
from infrastructure.database.connection import get_engine
from infrastructure.database.session import get_db_session
from presentation.api.main import app
from presentation.api.rate_limit import (
    LimitadorDeTaxa,
    _limitador_materiais,
    _limitador_perfis,
    _limitador_processamentos,
)

# Mesmo valor definido em tests/conftest.py: lido do ambiente em vez de
# duplicado, para não haver dois "tokens de teste" divergentes no repositório.
SERVICE_TOKEN = os.environ["SERVICE_TOKEN"]


@pytest_asyncio.fixture(autouse=True)
async def _sem_rate_limit_por_padrao() -> AsyncGenerator[None]:
    # Limitadores de /processamentos e /materiais são singletons (lru_cache); sem
    # neutralizá-los, testes fora de test_rate_limit.py disputam o mesmo contador e falham com 429.
    app.dependency_overrides[_limitador_processamentos] = lambda: LimitadorDeTaxa(
        limite=1_000_000, janela_segundos=60.0
    )
    app.dependency_overrides[_limitador_materiais] = lambda: LimitadorDeTaxa(
        limite=1_000_000, janela_segundos=60.0
    )
    app.dependency_overrides[_limitador_perfis] = lambda: LimitadorDeTaxa(
        limite=1_000_000, janela_segundos=60.0
    )
    yield
    app.dependency_overrides.pop(_limitador_perfis, None)
    app.dependency_overrides.pop(_limitador_processamentos, None)
    app.dependency_overrides.pop(_limitador_materiais, None)


@pytest_asyncio.fixture(autouse=True)
async def _tabelas() -> AsyncGenerator[None]:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def _conexao_isolada() -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    # AsyncClient sobre ASGITransport evita conflito de loop com a engine assíncrona cacheada.
    # Isolamento via transação externa com savepoints (create_savepoint), revertida no teardown.
    engine = get_engine()
    connection = await engine.connect()
    transacao_externa = await connection.begin()
    fabrica_de_sessao_do_teste = async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield fabrica_de_sessao_do_teste
    finally:
        await transacao_externa.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def client(
    _conexao_isolada: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient]:
    async def _get_db_session_isolada() -> AsyncGenerator[AsyncSession]:
        async with _conexao_isolada() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = _get_db_session_isolada

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db_session, None)


@pytest_asyncio.fixture
async def db_session(
    _conexao_isolada: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """Sessão para semear estado que a API sozinha não alcança (ex.: Processamento
    concluído com Material Personalizado, que só o Worker cria). Usa a mesma
    conexão/transação do fixture `client`, revertida junto no teardown."""
    async with _conexao_isolada() as session:
        yield session
        await session.commit()
