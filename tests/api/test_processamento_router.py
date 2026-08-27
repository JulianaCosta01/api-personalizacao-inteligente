from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest_asyncio
from httpx import AsyncClient

from presentation.api.main import app
from presentation.api.routers.material import _storage_material
from presentation.api.routers.perfil import _llm
from presentation.api.routers.processamento import _fila
from tests.api.conftest import SERVICE_TOKEN
from tests.unit.application.material.fakes import ObjectStorageFake
from tests.unit.application.perfil.fakes import LLMFake
from tests.unit.application.processamento.fakes import QueueFake

_AUTH = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
_PDF_VALIDO = b"%PDF-1.7\nconteudo qualquer"


@pytest_asyncio.fixture(autouse=True)
async def dependencias_externas_fake() -> AsyncGenerator[None]:
    app.dependency_overrides[_storage_material] = lambda: ObjectStorageFake()
    app.dependency_overrides[_llm] = lambda: LLMFake()
    yield
    app.dependency_overrides.pop(_storage_material, None)
    app.dependency_overrides.pop(_llm, None)


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


async def _criar_material(client: AsyncClient) -> str:
    resposta = await client.post(
        "/api/v1/materiais",
        data={"titulo": "Introdução a Grafos"},
        files={"arquivo": ("grafos.pdf", _PDF_VALIDO, "application/pdf")},
        headers=_AUTH,
    )
    return str(resposta.json()["id"])


async def _criar_perfil(client: AsyncClient, aluno_id: str) -> str:
    resposta = await client.post(
        f"/api/v1/alunos/{aluno_id}/perfil",
        json={
            "estilo_processamento": "Ativo",
            "percepcao": "Sensorial",
            "entrada": "Visual",
            "compreensao": "Sequencial",
        },
        headers=_AUTH,
    )
    return str(resposta.json()["id"])


async def _cenario_completo(client: AsyncClient) -> tuple[str, str]:
    aluno_id = await _criar_aluno(client)
    material_id = await _criar_material(client)
    await _criar_perfil(client, aluno_id)
    return aluno_id, material_id


async def test_post_autenticado_retorna_202(client: AsyncClient) -> None:
    aluno_id, material_id = await _cenario_completo(client)

    response = await client.post(
        "/api/v1/processamentos",
        json={"aluno_id": aluno_id, "material_didatico_id": material_id},
        headers=_AUTH,
    )

    assert response.status_code == 202
    corpo = response.json()
    assert corpo["aluno_id"] == aluno_id
    assert corpo["material_didatico_id"] == material_id
    assert corpo["status"] == "pendente"


async def test_post_sem_token_retorna_erro_de_autenticacao(client: AsyncClient) -> None:
    aluno_id, material_id = await _cenario_completo(client)

    response = await client.post(
        "/api/v1/processamentos",
        json={"aluno_id": aluno_id, "material_didatico_id": material_id},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_AUSENTE"


async def test_post_com_aluno_inexistente_retorna_404(client: AsyncClient) -> None:
    _, material_id = await _cenario_completo(client)

    response = await client.post(
        "/api/v1/processamentos",
        json={"aluno_id": str(uuid4()), "material_didatico_id": material_id},
        headers=_AUTH,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ALUNO_NAO_ENCONTRADO"


async def test_post_com_material_inexistente_retorna_404(client: AsyncClient) -> None:
    aluno_id = await _criar_aluno(client)
    await _criar_perfil(client, aluno_id)

    response = await client.post(
        "/api/v1/processamentos",
        json={"aluno_id": aluno_id, "material_didatico_id": str(uuid4())},
        headers=_AUTH,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MATERIAL_NAO_ENCONTRADO"


async def test_post_com_aluno_sem_perfil_retorna_422(client: AsyncClient) -> None:
    aluno_id = await _criar_aluno(client)
    material_id = await _criar_material(client)

    response = await client.post(
        "/api/v1/processamentos",
        json={"aluno_id": aluno_id, "material_didatico_id": material_id},
        headers=_AUTH,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PERFIL_NAO_CADASTRADO"


async def test_post_resolve_o_perfil_mais_recente(client: AsyncClient) -> None:
    aluno_id = await _criar_aluno(client)
    material_id = await _criar_material(client)
    await _criar_perfil(client, aluno_id)
    perfil_mais_recente_id = await _criar_perfil(client, aluno_id)

    response = await client.post(
        "/api/v1/processamentos",
        json={"aluno_id": aluno_id, "material_didatico_id": material_id},
        headers=_AUTH,
    )

    assert response.json()["perfil_id"] == perfil_mais_recente_id


async def test_post_com_falha_na_publicacao_retorna_500_com_processamento_em_erro(
    client: AsyncClient,
) -> None:
    aluno_id, material_id = await _cenario_completo(client)
    app.dependency_overrides[_fila] = lambda: QueueFake(levantar=True)
    try:
        response = await client.post(
            "/api/v1/processamentos",
            json={"aluno_id": aluno_id, "material_didatico_id": material_id},
            headers=_AUTH,
        )
    finally:
        app.dependency_overrides.pop(_fila, None)

    assert response.status_code == 500
    corpo = response.json()
    assert corpo["status"] == "erro"
    assert corpo["erro"] is not None


async def test_get_processamento_retorna_200(client: AsyncClient) -> None:
    aluno_id, material_id = await _cenario_completo(client)
    cadastro = await client.post(
        "/api/v1/processamentos",
        json={"aluno_id": aluno_id, "material_didatico_id": material_id},
        headers=_AUTH,
    )
    processamento_id = cadastro.json()["id"]

    response = await client.get(f"/api/v1/processamentos/{processamento_id}", headers=_AUTH)

    assert response.status_code == 200
    assert response.json()["id"] == processamento_id


async def test_get_processamento_inexistente_retorna_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/processamentos/{uuid4()}", headers=_AUTH)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROCESSAMENTO_NAO_ENCONTRADO"


async def test_get_sem_token_retorna_401(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/processamentos/{uuid4()}")

    assert response.status_code == 401


async def test_get_com_uuid_invalido_no_path_retorna_400(client: AsyncClient) -> None:
    response = await client.get("/api/v1/processamentos/nao-e-um-uuid", headers=_AUTH)

    assert response.status_code == 400


async def test_listagem_paginada(client: AsyncClient) -> None:
    aluno_id, material_id = await _cenario_completo(client)
    for _ in range(3):
        await client.post(
            "/api/v1/processamentos",
            json={"aluno_id": aluno_id, "material_didatico_id": material_id},
            headers=_AUTH,
        )

    primeira_pagina = await client.get(
        f"/api/v1/alunos/{aluno_id}/processamentos",
        params={"page": 1, "page_size": 2},
        headers=_AUTH,
    )
    segunda_pagina = await client.get(
        f"/api/v1/alunos/{aluno_id}/processamentos",
        params={"page": 2, "page_size": 2},
        headers=_AUTH,
    )

    assert primeira_pagina.json()["pagination"]["total_items"] == 3
    assert len(primeira_pagina.json()["data"]) == 2
    assert len(segunda_pagina.json()["data"]) == 1


async def test_listagem_aluno_inexistente_retorna_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/alunos/{uuid4()}/processamentos", headers=_AUTH)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ALUNO_NAO_ENCONTRADO"


async def test_listagem_com_uuid_invalido_no_path_retorna_400(client: AsyncClient) -> None:
    response = await client.get("/api/v1/alunos/nao-e-um-uuid/processamentos", headers=_AUTH)

    assert response.status_code == 400


async def test_listagem_sem_autenticacao_retorna_401(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/alunos/{uuid4()}/processamentos")

    assert response.status_code == 401


async def test_resposta_nao_expoe_detalhes_internos(client: AsyncClient) -> None:
    aluno_id, material_id = await _cenario_completo(client)

    response = await client.post(
        "/api/v1/processamentos",
        json={"aluno_id": aluno_id, "material_didatico_id": material_id},
        headers=_AUTH,
    )

    corpo = response.json()
    assert set(corpo.keys()) == {
        "id",
        "aluno_id",
        "material_didatico_id",
        "perfil_id",
        "status",
        "modelo_ia",
        "data_criacao",
        "inicio",
        "fim",
        "erro",
    }
    assert SERVICE_TOKEN not in response.text
