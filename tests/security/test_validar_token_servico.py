import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from core.config import Settings, get_settings
from core.exceptions import registrar_exception_handlers
from presentation.api.dependencies import validar_token_servico

_TOKEN_VALIDO = "token-correto-de-teste"


def _app_de_teste() -> FastAPI:
    app = FastAPI()
    registrar_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/db",
        service_token=_TOKEN_VALIDO,
    )

    @app.get("/protegido", dependencies=[Depends(validar_token_servico)])
    def _protegido() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app_de_teste())


def test_sem_header_authorization_retorna_401(client: TestClient) -> None:
    response = client.get("/protegido")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_AUSENTE"


def test_header_sem_prefixo_bearer_retorna_401(client: TestClient) -> None:
    response = client.get("/protegido", headers={"Authorization": _TOKEN_VALIDO})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_AUSENTE"


def test_token_incorreto_retorna_401(client: TestClient) -> None:
    response = client.get("/protegido", headers={"Authorization": "Bearer token-errado"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALIDO"


def test_token_vazio_apos_prefixo_retorna_401(client: TestClient) -> None:
    response = client.get("/protegido", headers={"Authorization": "Bearer "})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALIDO"


def test_token_correto_permite_acesso(client: TestClient) -> None:
    response = client.get("/protegido", headers={"Authorization": f"Bearer {_TOKEN_VALIDO}"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
