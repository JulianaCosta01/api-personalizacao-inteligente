from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from core.config import Settings
from presentation.api.main import app
from presentation.api.middleware import RequestIDMiddleware, SecurityHeadersMiddleware

client = TestClient(app)

_ORIGEM_PERMITIDA = "http://localhost:3000"
_ORIGEM_NAO_PERMITIDA = "https://origem-desconhecida.exemplo.com"


def _app_com_settings(settings: Settings) -> FastAPI:
    # Mesma composição de middlewares de create_app() (main.py), mas isolada a
    # partir de uma Settings construída no teste, sem mutar env real nem o app singleton.
    app_isolada = FastAPI()
    app_isolada.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_efetivas,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )
    app_isolada.add_middleware(RequestIDMiddleware)
    app_isolada.add_middleware(SecurityHeadersMiddleware, environment=settings.environment)

    @app_isolada.get("/rota-de-teste")
    def _rota() -> dict[str, bool]:
        return {"ok": True}

    return app_isolada


def _settings(environment: str, origens: list[str] | None = None) -> Settings:
    return Settings(environment=environment, cors_origins_permitidas=origens or [])


def test_origem_permitida_recebe_access_control_allow_origin() -> None:
    client_dev = TestClient(_app_com_settings(_settings("development")))

    response = client_dev.get("/rota-de-teste", headers={"Origin": _ORIGEM_PERMITIDA})

    assert response.headers["Access-Control-Allow-Origin"] == _ORIGEM_PERMITIDA


def test_origem_nao_permitida_nao_recebe_access_control_allow_origin() -> None:
    client_dev = TestClient(_app_com_settings(_settings("development")))

    response = client_dev.get("/rota-de-teste", headers={"Origin": _ORIGEM_NAO_PERMITIDA})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_options_retorna_headers_de_cors_sem_executar_a_rota() -> None:
    client_dev = TestClient(_app_com_settings(_settings("development")))

    response = client_dev.options(
        "/rota-de-teste",
        headers={
            "Origin": _ORIGEM_PERMITIDA,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == _ORIGEM_PERMITIDA
    # Corpo "OK" simples (nunca o JSON {"ok": True} da rota real) confirma que
    # quem respondeu foi o próprio CORSMiddleware, sem chegar à rota.
    assert response.text == "OK"


def test_metodo_permitido_e_refletido_no_preflight() -> None:
    client_dev = TestClient(_app_com_settings(_settings("development")))

    response = client_dev.options(
        "/rota-de-teste",
        headers={
            "Origin": _ORIGEM_PERMITIDA,
            "Access-Control-Request-Method": "PUT",
        },
    )

    metodos = response.headers["Access-Control-Allow-Methods"]
    assert "PUT" in metodos


def test_header_permitido_e_refletido_no_preflight() -> None:
    client_dev = TestClient(_app_com_settings(_settings("development")))

    response = client_dev.options(
        "/rota-de-teste",
        headers={
            "Origin": _ORIGEM_PERMITIDA,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert "authorization" in response.headers["Access-Control-Allow-Headers"].lower()


def test_requisicao_sem_origin_funciona_normalmente() -> None:
    # Chamada servidor-a-servidor real do Plugin Moodle:
    # sem header Origin, CORS não se aplica e a requisição segue normalmente.
    client_dev = TestClient(_app_com_settings(_settings("development")))

    response = client_dev.get("/rota-de-teste")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "Access-Control-Allow-Origin" not in response.headers


def test_allow_credentials_e_false() -> None:
    client_dev = TestClient(_app_com_settings(_settings("development")))

    response = client_dev.get("/rota-de-teste", headers={"Origin": _ORIGEM_PERMITIDA})

    assert "Access-Control-Allow-Credentials" not in response.headers


def test_production_sem_dominio_configurado_permanece_fechada() -> None:
    # Fail-closed: nenhuma origem inventada em produção enquanto o domínio
    # real do Moodle da UFMA não é configurado via CORS_ORIGINS_PERMITIDAS.
    client_producao = TestClient(_app_com_settings(_settings("production")))

    response = client_producao.get("/rota-de-teste", headers={"Origin": _ORIGEM_PERMITIDA})

    assert response.status_code == 200  # requisição em si não é bloqueada pela API
    assert "Access-Control-Allow-Origin" not in response.headers  # mas o navegador bloquearia


def test_production_com_dominio_configurado_aceita_a_origem_explicita() -> None:
    dominio_moodle = "https://moodle.ufma.br"
    client_producao = TestClient(
        _app_com_settings(_settings("production", origens=[dominio_moodle]))
    )

    response = client_producao.get("/rota-de-teste", headers={"Origin": dominio_moodle})

    assert response.headers["Access-Control-Allow-Origin"] == dominio_moodle


def test_development_aceita_os_localhost_definidos_por_default() -> None:
    client_dev = TestClient(_app_com_settings(_settings("development")))

    resposta_3000 = client_dev.get("/rota-de-teste", headers={"Origin": "http://localhost:3000"})
    resposta_8000 = client_dev.get("/rota-de-teste", headers={"Origin": "http://localhost:8000"})

    assert resposta_3000.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert resposta_8000.headers["Access-Control-Allow-Origin"] == "http://localhost:8000"


def test_x_request_id_preservado_com_cors_ativo() -> None:
    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:3000", "X-Request-ID": "meu-id-de-teste"},
    )

    assert response.headers["X-Request-ID"] == "meu-id-de-teste"


def test_headers_de_seguranca_da_task_2_preservados_com_cors_ativo() -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_headers_de_seguranca_preservados_ate_em_preflight_curto_circuitado() -> None:
    # CORSMiddleware é o mais interno dos três (main.py); mesmo respondendo ao preflight sem
    # chamar a rota, RequestIDMiddleware e SecurityHeadersMiddleware ainda pós-processam a resposta.
    client_dev = TestClient(_app_com_settings(_settings("development")))

    response = client_dev.options(
        "/rota-de-teste",
        headers={
            "Origin": _ORIGEM_PERMITIDA,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "X-Request-ID" in response.headers
