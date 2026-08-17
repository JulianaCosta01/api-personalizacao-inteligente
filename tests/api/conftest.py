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

# Mesmo valor definido em tests/conftest.py — lido do ambiente em vez de
# duplicado, para não haver dois "tokens de teste" divergentes no repositório.
SERVICE_TOKEN = os.environ["SERVICE_TOKEN"]


@pytest_asyncio.fixture(autouse=True)
async def _tabelas() -> AsyncGenerator[None]:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    # TestClient síncrono roda a app num event loop próprio, incompatível com
    # a engine assíncrona cacheada (get_engine): dá "Future attached to a
    # different loop". AsyncClient sobre ASGITransport mantém tudo no mesmo
    # loop da sessão de teste.
    #
    # get_db_session (produção) comita de verdade a cada requisição — é
    # intencional (Documento 4, §8) e continua acontecendo aqui do ponto de
    # vista da app. O que isola um teste do outro é ONDE esse commit acontece:
    # a sessão injetada é amarrada a uma única conexão que já tem uma
    # transação externa aberta antes da requisição, então cada "commit" de
    # requisição só libera um SAVEPOINT dentro dela (join_transaction_mode=
    # "create_savepoint", recomendado pela própria documentação do SQLAlchemy
    # para suítes de teste). Ao final do teste essa transação externa é
    # sempre revertida, então nada some persistido no Postgres efêmero para
    # contaminar as suítes de integração quando `pytest tests/` roda tudo
    # numa única sessão.
    engine = get_engine()
    connection = await engine.connect()
    transacao_externa = await connection.begin()
    fabrica_de_sessao_do_teste = async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )

    async def _get_db_session_isolada() -> AsyncGenerator[AsyncSession]:
        async with fabrica_de_sessao_do_teste() as session:
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
        await transacao_externa.rollback()
        await connection.close()
