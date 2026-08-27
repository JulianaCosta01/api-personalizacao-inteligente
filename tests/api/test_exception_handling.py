import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from core.exceptions import registrar_exception_handlers
from domain.shared.exceptions import (
    ConflitoDeEstadoError,
    RecursoNaoEncontradoError,
    RegraDeNegocioVioladaError,
)


class _Corpo(BaseModel):
    campo_obrigatorio: str


def _app_de_teste() -> FastAPI:
    app = FastAPI()
    registrar_exception_handlers(app)

    @app.get("/nao-encontrado")
    def _nao_encontrado() -> None:
        raise RecursoNaoEncontradoError(
            code="X_NAO_ENCONTRADO", message="não existe", details={"id": "1"}
        )

    @app.get("/regra-violada")
    def _regra_violada() -> None:
        raise RegraDeNegocioVioladaError(code="REGRA_X", message="regra violada")

    @app.get("/conflito")
    def _conflito() -> None:
        raise ConflitoDeEstadoError(code="ESTADO_X", message="estado conflitante")

    @app.get("/erro-interno")
    def _erro_interno() -> None:
        raise RuntimeError("falha inesperada")

    @app.get("/nao-autorizado")
    def _nao_autorizado() -> None:
        raise HTTPException(
            status_code=401, detail={"code": "TOKEN_INVALIDO", "message": "token inválido"}
        )

    @app.get("/http-exception-sem-envelope")
    def _http_exception_sem_envelope() -> None:
        raise HTTPException(status_code=403, detail="acesso negado")

    @app.post("/validado")
    def _validado(corpo: _Corpo) -> _Corpo:
        return corpo

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app_de_teste(), raise_server_exceptions=False)


def test_recurso_nao_encontrado_retorna_404_no_envelope_padrao(client: TestClient) -> None:
    response = client.get("/nao-encontrado")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "X_NAO_ENCONTRADO", "message": "não existe", "details": {"id": "1"}}
    }


def test_regra_de_negocio_violada_retorna_422(client: TestClient) -> None:
    response = client.get("/regra-violada")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REGRA_X"


def test_conflito_de_estado_retorna_409(client: TestClient) -> None:
    response = client.get("/conflito")

    assert response.status_code == 409


def test_excecao_nao_mapeada_retorna_500_sem_vazar_detalhes(client: TestClient) -> None:
    response = client.get("/erro-interno")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "ERRO_INTERNO"
    assert "falha inesperada" not in body["error"]["message"]


def test_corpo_invalido_retorna_400_no_envelope_padrao(client: TestClient) -> None:
    response = client.post("/validado", json={})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUISICAO_INVALIDA"


def test_http_exception_com_detail_estruturado_preserva_code_e_message(
    client: TestClient,
) -> None:
    response = client.get("/nao-autorizado")

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "TOKEN_INVALIDO", "message": "token inválido", "details": {}}
    }


def test_http_exception_com_detail_string_cai_no_envelope_generico(client: TestClient) -> None:
    response = client.get("/http-exception-sem-envelope")

    assert response.status_code == 403
    assert response.json() == {
        "error": {"code": "ERRO_HTTP", "message": "acesso negado", "details": {}}
    }
