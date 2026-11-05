from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from presentation.api.main import app
from presentation.api.routers.aluno import _repositorio_aluno
from tests.api.conftest import SERVICE_TOKEN
from tests.unit.application.aluno.fakes import AlunoRepositorioFake

_AUTH = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
_PEDIDO = {"nome": "Maria Souza", "email": "maria@discente.ufma.br", "matricula": "20240001"}


@pytest_asyncio.fixture
async def cliente() -> AsyncIterator[AsyncClient]:
    repositorio = AlunoRepositorioFake()  # sem banco: persiste em memória
    app.dependency_overrides[_repositorio_aluno] = lambda: repositorio
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c
    finally:
        app.dependency_overrides.pop(_repositorio_aluno, None)


async def test_cadastro_novo_devolve_o_registro_completo(cliente: AsyncClient) -> None:
    resposta = await cliente.post("/api/v1/alunos", json=_PEDIDO, headers=_AUTH)

    assert resposta.status_code == 201
    assert set(resposta.json()) >= {"id", "nome", "email", "matricula", "grupo_experimental"}


async def test_matricula_existente_devolve_somente_id_e_grupo(cliente: AsyncClient) -> None:
    primeiro = await cliente.post("/api/v1/alunos", json=_PEDIDO, headers=_AUTH)
    outro = {**_PEDIDO, "nome": "Outra Pessoa", "email": "outra@discente.ufma.br"}

    segundo = await cliente.post("/api/v1/alunos", json=outro, headers=_AUTH)

    assert segundo.status_code == 200
    assert segundo.json() == {
        "id": primeiro.json()["id"],
        "grupo_experimental": primeiro.json()["grupo_experimental"],
    }
    assert "Maria" not in segundo.text and "maria@" not in segundo.text
    assert "Outra Pessoa" not in segundo.text


async def test_dados_completos_continuam_em_get_por_id(cliente: AsyncClient) -> None:
    criado = (await cliente.post("/api/v1/alunos", json=_PEDIDO, headers=_AUTH)).json()

    consulta = await cliente.get(f"/api/v1/alunos/{criado['id']}", headers=_AUTH)

    assert consulta.status_code == 200
    assert consulta.json()["email"] == _PEDIDO["email"]


async def test_campos_acima_do_limite_da_coluna_retornam_400_e_nao_500(
    cliente: AsyncClient,
) -> None:
    resposta = await cliente.post(
        "/api/v1/alunos", json={**_PEDIDO, "matricula": "m" * 21}, headers=_AUTH
    )
    assert resposta.status_code == 400
    assert resposta.json()["error"]["code"] == "REQUISICAO_INVALIDA"
