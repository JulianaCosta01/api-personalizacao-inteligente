import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from core.config import get_settings
from presentation.api import main


def _app_para(monkeypatch: pytest.MonkeyPatch, ambiente: str) -> FastAPI:
    configuracao = get_settings().model_copy(update={"environment": ambiente})
    monkeypatch.setattr(main, "get_settings", lambda: configuracao)
    return main.create_app()


@pytest.mark.parametrize("ambiente", ["staging", "production"])
@pytest.mark.parametrize("caminho", ["/docs", "/redoc", "/openapi.json"])
async def test_documentacao_nao_e_publicada_fora_de_desenvolvimento(
    monkeypatch: pytest.MonkeyPatch, ambiente: str, caminho: str
) -> None:
    app = _app_para(monkeypatch, ambiente)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as cliente:
        assert (await cliente.get(caminho)).status_code == 404


@pytest.mark.parametrize("caminho", ["/docs", "/redoc", "/openapi.json"])
async def test_documentacao_segue_disponivel_em_desenvolvimento(
    monkeypatch: pytest.MonkeyPatch, caminho: str
) -> None:
    app = _app_para(monkeypatch, "development")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as cliente:
        assert (await cliente.get(caminho)).status_code == 200


async def test_health_continua_funcionando_em_producao(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app_para(monkeypatch, "production")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as cliente:
        resposta = await cliente.get("/health")
    assert resposta.status_code == 200
    assert resposta.headers["Strict-Transport-Security"].startswith("max-age=")
