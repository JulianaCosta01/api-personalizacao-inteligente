from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from presentation.api.rate_limit import LimitadorDeTaxa, _limitador_perfis, limitar_perfis
from presentation.api.routers.perfil import router as router_de_perfil
from tests.api.conftest import SERVICE_TOKEN

_AUTH = {"Authorization": f"Bearer {SERVICE_TOKEN}"}


def test_post_perfil_esta_protegido_pelo_limite_de_taxa() -> None:
    rota = next(
        r
        for r in router_de_perfil.routes
        if getattr(r, "path", "").endswith("/{aluno_id}/perfil")
        and "POST" in getattr(r, "methods", set())
    )
    assert any(d.call is limitar_perfis for d in rota.dependant.dependencies)  # type: ignore[attr-defined]


async def test_excedido_o_limite_responde_429_com_o_envelope_padrao() -> None:
    app = FastAPI()
    limitador = LimitadorDeTaxa(limite=2, janela_segundos=60.0)
    app.dependency_overrides[_limitador_perfis] = lambda: limitador

    @app.post("/perfil", dependencies=[Depends(limitar_perfis)])
    async def perfil() -> dict[str, bool]:
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as cliente:
        primeira = await cliente.post("/perfil", headers=_AUTH)
        segunda = await cliente.post("/perfil", headers=_AUTH)
        terceira = await cliente.post("/perfil", headers=_AUTH)

    assert (primeira.status_code, segunda.status_code) == (200, 200)
    assert terceira.status_code == 429
    assert terceira.json()["detail"]["code"] == "LIMITE_DE_REQUISICOES_EXCEDIDO"
