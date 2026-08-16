from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest_asyncio
from httpx import AsyncClient, Response
from tests.api.conftest import SERVICE_TOKEN
from tests.unit.application.material.fakes import ObjectStorageFake

from core.config import get_settings
from presentation.api.main import app
from presentation.api.routers.material import _storage_material

_AUTH = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
_PDF_VALIDO = b"%PDF-1.7\nconteudo qualquer"


@pytest_asyncio.fixture
async def storage_fake() -> AsyncGenerator[ObjectStorageFake]:
    fake = ObjectStorageFake()
    app.dependency_overrides[_storage_material] = lambda: fake
    yield fake
    app.dependency_overrides.pop(_storage_material, None)


def _arquivo(
    nome: str = "grafos.pdf", conteudo: bytes = _PDF_VALIDO, content_type: str = "application/pdf"
) -> dict[str, tuple[str, bytes, str]]:
    return {"arquivo": (nome, conteudo, content_type)}


async def _cadastrar(
    client: AsyncClient,
    titulo: str = "Introdução a Grafos",
    nome: str = "grafos.pdf",
    conteudo: bytes = _PDF_VALIDO,
    content_type: str = "application/pdf",
) -> Response:
    return await client.post(
        "/api/v1/materiais",
        data={"titulo": titulo},
        files=_arquivo(nome, conteudo, content_type),
        headers=_AUTH,
    )


async def test_post_autenticado_com_pdf_valido_retorna_201(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    response = await _cadastrar(client)

    assert response.status_code == 201
    corpo = response.json()
    assert corpo["titulo"] == "Introdução a Grafos"
    assert corpo["versao"] == 1
    assert corpo["tipo_arquivo"] == "application/pdf"
    assert len(storage_fake.salvos) == 1


async def test_post_sem_token_retorna_401(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    response = await client.post("/api/v1/materiais", data={"titulo": "X"}, files=_arquivo())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_AUSENTE"


async def test_post_com_token_invalido_retorna_401(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    response = await client.post(
        "/api/v1/materiais",
        data={"titulo": "X"},
        files=_arquivo(),
        headers={"Authorization": "Bearer token-errado"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALIDO"


async def test_post_arquivo_que_nao_e_pdf_retorna_400(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    response = await _cadastrar(client, conteudo=b"isto nao e um pdf")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ARQUIVO_INVALIDO"
    assert storage_fake.salvos == {}


async def test_post_com_extensao_pdf_enganosa_retorna_400(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    # Nome termina em .pdf, mas o conteúdo não é um PDF de verdade — a
    # extensão não pode ser o que decide a validade do arquivo.
    response = await _cadastrar(client, nome="relatorio.pdf", conteudo=b"conteudo forjado")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ARQUIVO_INVALIDO"


async def test_post_com_pdf_real_e_extensao_diferente_e_aceito(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    response = await _cadastrar(client, nome="material.bin")

    assert response.status_code == 201


async def test_post_com_content_type_enganoso_retorna_400(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    # Content-Type declarado como PDF, mas os bytes não são um PDF real.
    response = await _cadastrar(client, conteudo=b"nao e pdf", content_type="application/pdf")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ARQUIVO_INVALIDO"


async def test_post_arquivo_acima_do_limite_retorna_400(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    settings_reduzido = get_settings().model_copy(update={"material_tamanho_maximo_bytes": 10})
    app.dependency_overrides[get_settings] = lambda: settings_reduzido
    try:
        response = await _cadastrar(client)
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ARQUIVO_MUITO_GRANDE"
    assert storage_fake.salvos == {}


async def test_post_com_nome_de_arquivo_malicioso_nao_afeta_a_chave_de_storage(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    response = await _cadastrar(client, nome="../../etc/passwd.pdf")

    assert response.status_code == 201
    chave = next(iter(storage_fake.salvos))
    assert ".." not in chave
    assert not chave.startswith("/")


async def test_post_resposta_nao_expoe_caminho_interno_do_storage(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    response = await _cadastrar(client)

    corpo = response.json()
    assert "caminho_storage" not in corpo
    assert "storage_service_key" not in corpo


async def test_post_com_material_original_id_incrementa_versao_e_retorna_200(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    original = await _cadastrar(client)
    material_id = original.json()["id"]

    revisao = await client.post(
        "/api/v1/materiais",
        data={"titulo": "Introdução a Grafos", "material_original_id": material_id},
        files=_arquivo(nome="grafos_v2.pdf"),
        headers=_AUTH,
    )

    assert revisao.status_code == 200
    corpo = revisao.json()
    assert corpo["id"] == material_id
    assert corpo["versao"] == 2


async def test_get_por_id_existente_retorna_material(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    cadastro = await _cadastrar(client)
    material_id = cadastro.json()["id"]

    response = await client.get(f"/api/v1/materiais/{material_id}", headers=_AUTH)

    assert response.status_code == 200
    corpo = response.json()
    assert set(corpo.keys()) == {
        "id",
        "titulo",
        "nome_arquivo",
        "tipo_arquivo",
        "versao",
        "data_upload",
    }


async def test_get_por_id_inexistente_retorna_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/materiais/{uuid4()}", headers=_AUTH)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MATERIAL_NAO_ENCONTRADO"


async def test_get_por_id_sem_autenticacao_retorna_401(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/materiais/{uuid4()}")

    assert response.status_code == 401


async def test_get_com_uuid_invalido_no_path_retorna_400(client: AsyncClient) -> None:
    response = await client.get("/api/v1/materiais/nao-e-um-uuid", headers=_AUTH)

    assert response.status_code == 400


async def test_listagem_retorna_envelope_com_data_e_pagination(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    await _cadastrar(client, titulo="Material Único")

    response = await client.get("/api/v1/materiais", headers=_AUTH)

    assert response.status_code == 200
    corpo = response.json()
    assert "data" in corpo and "pagination" in corpo
    assert set(corpo["pagination"].keys()) == {"page", "page_size", "total_items", "total_pages"}


async def test_listagem_sem_autenticacao_retorna_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/materiais")

    assert response.status_code == 401


async def test_listagem_pagina_resultados(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    prefixo = str(uuid4())
    for i in range(3):
        await _cadastrar(client, titulo=f"{prefixo} {i}")

    primeira_pagina = await client.get(
        "/api/v1/materiais", params={"page": 1, "page_size": 2, "titulo": prefixo}, headers=_AUTH
    )
    segunda_pagina = await client.get(
        "/api/v1/materiais", params={"page": 2, "page_size": 2, "titulo": prefixo}, headers=_AUTH
    )

    assert len(primeira_pagina.json()["data"]) == 2
    assert primeira_pagina.json()["pagination"]["total_items"] == 3
    assert len(segunda_pagina.json()["data"]) == 1


async def test_listagem_filtra_por_titulo(
    client: AsyncClient, storage_fake: ObjectStorageFake
) -> None:
    prefixo = str(uuid4())
    await _cadastrar(client, titulo=f"{prefixo} Grafos")
    await _cadastrar(client, titulo=f"{prefixo} Árvores")

    response = await client.get(
        "/api/v1/materiais", params={"titulo": f"{prefixo} Grafos"}, headers=_AUTH
    )

    corpo = response.json()
    assert corpo["pagination"]["total_items"] == 1
    assert corpo["data"][0]["titulo"] == f"{prefixo} Grafos"
