from fastapi.testclient import TestClient
from httpx import AsyncClient

from core.config import Settings, get_settings
from presentation.api.main import app
from presentation.api.routers.health import ResultadoProntidao, verificar_prontidao


def test_health_retorna_200_e_status_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "development"}


def test_health_propaga_request_id_na_resposta() -> None:
    client = TestClient(app)

    response = client.get("/health", headers={"X-Request-ID": "meu-id-de-teste"})

    assert response.headers["X-Request-ID"] == "meu-id-de-teste"


def test_health_reflete_settings_injetada_via_dependency_override() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(environment="production")
    try:
        response = TestClient(app).get("/health")
    finally:
        app.dependency_overrides.clear()

    assert response.json()["environment"] == "production"


# /ready usa get_engine() diretamente (Fase 11) — precisa do cliente
# assíncrono sobre ASGITransport (fixture `client`, tests/api/conftest.py),
# não do TestClient síncrono usado acima para /health: a engine assíncrona
# cacheada por get_engine() já causa "Future attached to a different loop"
# com TestClient síncrono, exatamente o problema que a fixture `client` existe
# para evitar (ver comentário em tests/api/conftest.py).


async def test_ready_retorna_200_quando_banco_e_fila_estao_disponiveis(
    client: AsyncClient,
) -> None:
    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok", "queue": "ok"}


async def test_ready_retorna_503_quando_banco_indisponivel(client: AsyncClient) -> None:
    # Sem derrubar um Postgres real: override da dependency, mesmo padrão já
    # usado neste projeto para simular estado sem depender de infraestrutura
    # externa de verdade.
    app.dependency_overrides[verificar_prontidao] = lambda: ResultadoProntidao(
        banco_ok=False, fila_ok=False
    )
    try:
        response = await client.get("/ready")
    finally:
        app.dependency_overrides.pop(verificar_prontidao, None)

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "error", "queue": "error"}


async def test_ready_reporta_fila_indisponivel_quando_so_a_fila_falha(
    client: AsyncClient,
) -> None:
    app.dependency_overrides[verificar_prontidao] = lambda: ResultadoProntidao(
        banco_ok=True, fila_ok=False
    )
    try:
        response = await client.get("/ready")
    finally:
        app.dependency_overrides.pop(verificar_prontidao, None)

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "ok", "queue": "error"}


async def test_ready_nao_expoe_informacao_sensivel_na_falha(client: AsyncClient) -> None:
    app.dependency_overrides[verificar_prontidao] = lambda: ResultadoProntidao(
        banco_ok=False, fila_ok=False
    )
    try:
        response = await client.get("/ready")
    finally:
        app.dependency_overrides.pop(verificar_prontidao, None)

    corpo = response.text.lower()
    for termo_proibido in (
        "postgresql",
        "asyncpg",
        "database_url",
        "password",
        "senha",
        "traceback",
        "localhost",
    ):
        assert termo_proibido not in corpo


def test_ready_nao_altera_o_comportamento_existente_de_health() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "development"}
