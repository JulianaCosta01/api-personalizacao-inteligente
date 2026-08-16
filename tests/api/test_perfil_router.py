import asyncio
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest_asyncio
from httpx import AsyncClient, Response
from tests.api.conftest import SERVICE_TOKEN
from tests.unit.application.perfil.fakes import LLMFake

from core.config import get_settings
from presentation.api.main import app
from presentation.api.routers.perfil import _llm

_AUTH = {"Authorization": f"Bearer {SERVICE_TOKEN}"}


@pytest_asyncio.fixture
async def llm_fake() -> AsyncGenerator[LLMFake]:
    fake = LLMFake()
    app.dependency_overrides[_llm] = lambda: fake
    yield fake
    app.dependency_overrides.pop(_llm, None)


def _payload_perfil() -> dict[str, str]:
    return {
        "estilo_processamento": "Ativo",
        "percepcao": "Sensorial",
        "entrada": "Visual",
        "compreensao": "Sequencial",
    }


async def _criar_aluno(client: AsyncClient) -> str:
    resposta = await client.post(
        "/api/v1/alunos",
        json={
            "nome": "Kristiano Fernandes Plácido",
            "email": "kristiano@discente.ufma.br",
            "matricula": str(uuid4())[:20],
        },
        headers=_AUTH,
    )
    return str(resposta.json()["id"])


async def _cadastrar_perfil(client: AsyncClient, aluno_id: str) -> Response:
    return await client.post(
        f"/api/v1/alunos/{aluno_id}/perfil", json=_payload_perfil(), headers=_AUTH
    )


async def test_post_autenticado_retorna_201(client: AsyncClient, llm_fake: LLMFake) -> None:
    aluno_id = await _criar_aluno(client)

    response = await _cadastrar_perfil(client, aluno_id)

    assert response.status_code == 201
    corpo = response.json()
    assert corpo["aluno_id"] == aluno_id
    assert corpo["estilo_processamento"] == "Ativo"


async def test_post_sem_token_retorna_erro_de_autenticacao(
    client: AsyncClient, llm_fake: LLMFake
) -> None:
    aluno_id = await _criar_aluno(client)

    response = await client.post(f"/api/v1/alunos/{aluno_id}/perfil", json=_payload_perfil())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_AUSENTE"


async def test_post_com_aluno_inexistente_retorna_404(
    client: AsyncClient, llm_fake: LLMFake
) -> None:
    response = await _cadastrar_perfil(client, str(uuid4()))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ALUNO_NAO_ENCONTRADO"


async def test_post_retorna_descricao_llm_quando_gemini_funciona(
    client: AsyncClient, llm_fake: LLMFake
) -> None:
    llm_fake.descricao = "Perfil com forte tendência à experimentação prática."
    aluno_id = await _criar_aluno(client)

    response = await _cadastrar_perfil(client, aluno_id)

    assert response.status_code == 201
    corpo = response.json()
    assert corpo["descricao_llm"] == "Perfil com forte tendência à experimentação prática."


async def test_post_com_falha_do_gemini_retorna_201_com_descricao_llm_nula(
    client: AsyncClient, llm_fake: LLMFake
) -> None:
    llm_fake.levantar = True
    aluno_id = await _criar_aluno(client)

    response = await _cadastrar_perfil(client, aluno_id)

    assert response.status_code == 201
    assert response.json()["descricao_llm"] is None


async def test_get_retorna_perfil_mais_recente(client: AsyncClient, llm_fake: LLMFake) -> None:
    aluno_id = await _criar_aluno(client)
    await _cadastrar_perfil(client, aluno_id)
    await asyncio.sleep(0.01)
    ultimo = await _cadastrar_perfil(client, aluno_id)

    response = await client.get(f"/api/v1/alunos/{aluno_id}/perfil", headers=_AUTH)

    assert response.status_code == 200
    assert response.json()["id"] == ultimo.json()["id"]


async def test_get_aluno_sem_perfil_retorna_404(client: AsyncClient) -> None:
    aluno_id = await _criar_aluno(client)

    response = await client.get(f"/api/v1/alunos/{aluno_id}/perfil", headers=_AUTH)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PERFIL_NAO_ENCONTRADO"


async def test_get_aluno_inexistente_retorna_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/alunos/{uuid4()}/perfil", headers=_AUTH)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ALUNO_NAO_ENCONTRADO"


async def test_listagem_pagina_resultados(client: AsyncClient, llm_fake: LLMFake) -> None:
    aluno_id = await _criar_aluno(client)
    for _ in range(3):
        await _cadastrar_perfil(client, aluno_id)
        await asyncio.sleep(0.01)

    primeira_pagina = await client.get(
        f"/api/v1/alunos/{aluno_id}/perfis", params={"page": 1, "page_size": 2}, headers=_AUTH
    )
    segunda_pagina = await client.get(
        f"/api/v1/alunos/{aluno_id}/perfis", params={"page": 2, "page_size": 2}, headers=_AUTH
    )

    assert primeira_pagina.json()["pagination"]["total_items"] == 3
    assert len(primeira_pagina.json()["data"]) == 2
    assert len(segunda_pagina.json()["data"]) == 1


async def test_listagem_ordena_do_mais_recente_para_o_mais_antigo(
    client: AsyncClient, llm_fake: LLMFake
) -> None:
    aluno_id = await _criar_aluno(client)
    primeiro = await _cadastrar_perfil(client, aluno_id)
    await asyncio.sleep(0.01)
    segundo = await _cadastrar_perfil(client, aluno_id)
    await asyncio.sleep(0.01)
    terceiro = await _cadastrar_perfil(client, aluno_id)

    response = await client.get(f"/api/v1/alunos/{aluno_id}/perfis", headers=_AUTH)

    ids = [item["id"] for item in response.json()["data"]]
    assert ids == [terceiro.json()["id"], segundo.json()["id"], primeiro.json()["id"]]


async def test_uuid_invalido_no_path_retorna_400(client: AsyncClient) -> None:
    response = await client.get("/api/v1/alunos/nao-e-um-uuid/perfil", headers=_AUTH)

    assert response.status_code == 400


async def test_resposta_nao_expoe_segredos_ou_detalhes_do_gemini(
    client: AsyncClient, llm_fake: LLMFake
) -> None:
    aluno_id = await _criar_aluno(client)

    response = await _cadastrar_perfil(client, aluno_id)

    corpo = response.json()
    assert set(corpo.keys()) == {
        "id",
        "aluno_id",
        "estilo_processamento",
        "percepcao",
        "entrada",
        "compreensao",
        "descricao_llm",
        "data_atualizacao",
    }
    assert get_settings().gemini_api_key not in response.text
    assert "gemini" not in response.text.lower()
