from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from core.config import get_settings
from presentation.api.main import app as app_real
from presentation.api.protecao_corpo import FOLGA_DO_MULTIPART_BYTES, ProtecaoDeCorpoMiddleware
from tests.api.conftest import SERVICE_TOKEN  # mesmo token de teste definido em tests/conftest.py

_AUTH = {"Authorization": f"Bearer {SERVICE_TOKEN}"}


class _Corpo(BaseModel):
    texto: str


def _app_de_teste(parseou: list[int]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(ProtecaoDeCorpoMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "sim"}

    @app.post("/api/v1/json")
    async def json_(corpo: _Corpo) -> dict[str, int]:
        parseou.append(1)
        return {"n": len(corpo.texto)}

    @app.post("/api/v1/materiais")
    async def upload(arquivo: UploadFile = File(...)) -> dict[str, int]:
        parseou.append(1)
        return {"n": len(await arquivo.read())}

    @app.options("/api/v1/json")
    async def opcoes() -> JSONResponse:
        return JSONResponse({})

    return app


@pytest.fixture
def parseou() -> list[int]:
    return []


@pytest.fixture
def cliente(parseou: list[int]) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=_app_de_teste(parseou)), base_url="http://testserver"
    )


def _limite_upload() -> int:
    return get_settings().material_tamanho_maximo_bytes + FOLGA_DO_MULTIPART_BYTES


def _limite_json() -> int:
    return get_settings().corpo_json_tamanho_maximo_bytes


# Autenticação antes do parse


async def test_sem_token_responde_401_sem_ler_nem_interpretar_o_corpo(
    cliente: AsyncClient, parseou: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    import starlette.formparsers as formparsers

    chamadas: list[int] = []
    original = formparsers.MultiPartParser.parse

    async def espiao(self: Any) -> Any:
        chamadas.append(1)
        return await original(self)

    monkeypatch.setattr(formparsers.MultiPartParser, "parse", espiao)
    async with cliente:
        resposta = await cliente.post(
            "/api/v1/materiais", files={"arquivo": ("a.pdf", b"%PDF-" + b"0" * (3 * 1024 * 1024))}
        )

    assert resposta.status_code == 401
    assert resposta.json()["error"]["code"] == "TOKEN_AUSENTE"
    assert chamadas == [] and parseou == []


@pytest.mark.parametrize(
    ("cabecalho", "codigo"),
    [
        ({}, "TOKEN_AUSENTE"),
        ({"Authorization": "Basic abc"}, "TOKEN_AUSENTE"),
        ({"Authorization": "Bearer errado"}, "TOKEN_INVALIDO"),
    ],
)
async def test_token_ausente_ou_invalido_e_recusado(
    cliente: AsyncClient, parseou: list[int], cabecalho: dict[str, str], codigo: str
) -> None:
    async with cliente:
        resposta = await cliente.post("/api/v1/json", json={"texto": "x"}, headers=cabecalho)
    assert resposta.status_code == 401
    assert resposta.json()["error"]["code"] == codigo
    assert parseou == []


async def test_token_com_caractere_nao_ascii_e_401_e_nao_500(cliente: AsyncClient) -> None:
    async with cliente:
        resposta = await cliente.get(
            "/api/v1/ping", headers=[(b"Authorization", "Bearer tókén".encode("latin-1"))]
        )
    assert resposta.status_code == 401


# Limite de tamanho


async def test_content_length_acima_do_limite_json_responde_413_sem_ler_o_corpo(
    cliente: AsyncClient, parseou: list[int]
) -> None:
    async with cliente:
        resposta = await cliente.post(
            "/api/v1/json", json={"texto": "x" * (_limite_json() + 10)}, headers=_AUTH
        )
    assert resposta.status_code == 413
    assert resposta.json()["error"]["code"] == "CORPO_MUITO_GRANDE"
    assert parseou == []


async def test_content_length_acima_do_limite_de_upload_responde_413(
    cliente: AsyncClient, parseou: list[int]
) -> None:
    conteudo = b"%PDF-" + b"0" * (_limite_upload() + 1)
    async with cliente:
        resposta = await cliente.post(
            "/api/v1/materiais", files={"arquivo": ("a.pdf", conteudo)}, headers=_AUTH
        )
    assert resposta.status_code == 413
    assert parseou == []


async def test_corpo_sem_content_length_acima_do_limite_responde_413(
    cliente: AsyncClient, parseou: list[int]
) -> None:
    async def blocos() -> AsyncIterator[bytes]:
        for _ in range((_limite_json() // 65536) + 3):
            yield b"x" * 65536

    async with cliente:
        resposta = await cliente.post(
            "/api/v1/json",
            content=blocos(),
            headers={**_AUTH, "Content-Type": "application/json"},  # httpx usa chunked
        )
    assert resposta.status_code == 413
    assert parseou == []


async def test_corpo_chunked_sem_content_length_nao_e_lido_alem_do_limite() -> None:
    # Chamada direta ao ASGI: sem Content-Length e com um fluxo "infinito" de blocos; o
    # middleware deve parar logo após o limite, sem pedir mais blocos do que o necessário.
    pedidos = 0
    respostas: list[dict[str, Any]] = []
    chegou_ao_app = False

    async def app(scope: Any, receive: Any, send: Any) -> None:
        nonlocal chegou_ao_app
        chegou_ao_app = True

    async def receive() -> dict[str, Any]:
        nonlocal pedidos
        pedidos += 1
        return {"type": "http.request", "body": b"x" * 65536, "more_body": True}

    async def send(mensagem: dict[str, Any]) -> None:
        respostas.append(mensagem)

    escopo = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/json",
        "headers": [(b"authorization", f"Bearer {SERVICE_TOKEN}".encode())],
    }
    await ProtecaoDeCorpoMiddleware(app)(escopo, receive, send)  # type: ignore[arg-type]

    assert respostas[0]["status"] == 413 and not chegou_ao_app
    assert pedidos <= (_limite_json() // 65536) + 2


async def test_upload_dentro_do_limite_e_json_valido_chegam_ao_aplicativo(
    cliente: AsyncClient, parseou: list[int]
) -> None:
    async with cliente:
        up = await cliente.post(
            "/api/v1/materiais",
            files={"arquivo": ("a.pdf", b"%PDF-" + b"0" * (2 * 1024 * 1024))},
            headers=_AUTH,
        )
        js = await cliente.post("/api/v1/json", json={"texto": "olá"}, headers=_AUTH)
        grande = await cliente.post(
            "/api/v1/materiais",
            files={
                "arquivo": (
                    "a.pdf",
                    b"%PDF-" + b"0" * (get_settings().material_tamanho_maximo_bytes - 5),
                )
            },
            headers=_AUTH,
        )
    assert up.status_code == 200 and up.json()["n"] == 2 * 1024 * 1024 + 5
    assert js.status_code == 200 and js.json() == {"n": 3}
    assert grande.status_code == 200  # exatamente no limite do arquivo: aceito
    assert len(parseou) == 3


async def test_get_sem_corpo_com_token_passa(cliente: AsyncClient) -> None:
    async with cliente:
        resposta = await cliente.get("/api/v1/ping", headers=_AUTH)
    assert resposta.status_code == 200


# O que não é protegido


async def test_health_e_options_nao_exigem_token(cliente: AsyncClient) -> None:
    async with cliente:
        saude = await cliente.get("/health")
        preflight = await cliente.options("/api/v1/json")
    assert saude.status_code == 200
    assert preflight.status_code == 200


# No aplicativo real


async def test_app_real_nao_autenticado_recebe_401_com_headers_de_seguranca() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app_real), base_url="http://testserver"
    ) as cliente:
        resposta = await cliente.post("/api/v1/alunos", json={"nome": "x" * 5_000_000})
    assert resposta.status_code == 401
    assert resposta.headers["X-Content-Type-Options"] == "nosniff"
    assert "X-Request-ID" in resposta.headers


async def test_app_real_corpo_enorme_autenticado_recebe_413() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app_real), base_url="http://testserver"
    ) as cliente:
        resposta = await cliente.post(
            "/api/v1/alunos", json={"nome": "x" * (_limite_json() + 1)}, headers=_AUTH
        )
    assert resposta.status_code == 413


async def test_app_real_health_continua_publico() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app_real), base_url="http://testserver"
    ) as cliente:
        resposta = await cliente.get("/health")
    assert resposta.status_code == 200
