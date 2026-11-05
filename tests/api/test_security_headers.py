from fastapi import FastAPI
from fastapi.testclient import TestClient

from presentation.api.main import app
from presentation.api.middleware import SecurityHeadersMiddleware

client = TestClient(app)


def _app_com_ambiente(environment: str) -> FastAPI:
    # Strict-Transport-Security é decidido no registro do middleware (Settings resolvida
    # uma vez em create_app), sem dependency_overrides: daí a app isolada para "production".
    app_isolada = FastAPI()
    app_isolada.add_middleware(SecurityHeadersMiddleware, environment=environment)

    @app_isolada.get("/rota-de-teste")
    def _rota() -> dict[str, bool]:
        return {"ok": True}

    return app_isolada


def test_x_content_type_options_presente_e_com_valor_correto() -> None:
    response = client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_x_frame_options_presente_e_com_valor_correto() -> None:
    response = client.get("/health")

    assert response.headers["X-Frame-Options"] == "DENY"


def test_hsts_presente_em_production() -> None:
    client_producao = TestClient(_app_com_ambiente("production"))

    response = client_producao.get("/rota-de-teste")

    assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_hsts_ausente_fora_de_production() -> None:
    client_dev = TestClient(_app_com_ambiente("development"))

    response = client_dev.get("/rota-de-teste")

    assert "Strict-Transport-Security" not in response.headers


def test_hsts_ausente_em_staging() -> None:
    # "production" é o único gatilho; staging não deve herdar HSTS por engano
    # caso algum código algum dia compare "!= development".
    client_staging = TestClient(_app_com_ambiente("staging"))

    response = client_staging.get("/rota-de-teste")

    assert "Strict-Transport-Security" not in response.headers


def test_headers_presentes_no_docs() -> None:
    response = client.get("/docs")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_headers_presentes_no_redoc() -> None:
    response = client.get("/redoc")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_headers_presentes_no_openapi_json() -> None:
    response = client.get("/openapi.json")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_docs_redoc_openapi_continuam_acessiveis() -> None:
    # Confirma explicitamente que o middleware não quebrou nenhuma das três
    # rotas.
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_x_request_id_preservado_junto_com_os_novos_headers() -> None:
    response = client.get("/health", headers={"X-Request-ID": "meu-id-de-teste"})

    assert response.headers["X-Request-ID"] == "meu-id-de-teste"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
