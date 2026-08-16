import os
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import infrastructure.database.models  # noqa: F401 -- popula Base.metadata
from infrastructure.database.base import Base
from infrastructure.database.connection import get_engine
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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
