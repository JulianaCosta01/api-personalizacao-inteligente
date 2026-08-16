from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo
from infrastructure.database.material.material_repository import MaterialRepositorySQLAlchemy


def _material(titulo: str = "Introdução a Grafos") -> MaterialDidatico:
    return MaterialDidatico(
        id=uuid4(),
        titulo=titulo,
        nome_arquivo="grafos.pdf",
        tipo_arquivo=TipoArquivo.PDF,
        caminho_storage=f"materiais/{uuid4()}.pdf",
        versao=1,
        data_upload=datetime.now(UTC),
    )


async def test_adiciona_e_busca_por_id(db_session: AsyncSession) -> None:
    repositorio = MaterialRepositorySQLAlchemy(db_session)
    material = _material()

    await repositorio.adicionar(material)
    encontrado = await repositorio.obter_por_id(material.id)

    assert encontrado is not None
    assert encontrado.titulo == material.titulo
    assert encontrado.tipo_arquivo == TipoArquivo.PDF


async def test_obter_por_id_retorna_none_quando_nao_existe(db_session: AsyncSession) -> None:
    repositorio = MaterialRepositorySQLAlchemy(db_session)

    assert await repositorio.obter_por_id(uuid4()) is None


async def test_atualizar_persiste_revisao(db_session: AsyncSession) -> None:
    repositorio = MaterialRepositorySQLAlchemy(db_session)
    material = _material()
    await repositorio.adicionar(material)

    material.revisar(
        nome_arquivo="grafos_v2.pdf",
        tipo_arquivo=TipoArquivo.PDF,
        caminho_storage=f"materiais/{uuid4()}.pdf",
        data_upload=datetime.now(UTC),
    )
    await repositorio.atualizar(material)

    encontrado = await repositorio.obter_por_id(material.id)
    assert encontrado is not None
    assert encontrado.versao == 2
    assert encontrado.nome_arquivo == "grafos_v2.pdf"


async def test_atualizar_material_inexistente_levanta_lookup_error(
    db_session: AsyncSession,
) -> None:
    repositorio = MaterialRepositorySQLAlchemy(db_session)

    with pytest.raises(LookupError):
        await repositorio.atualizar(_material())


async def test_listar_retorna_total_e_itens_paginados(db_session: AsyncSession) -> None:
    # Filtra pelo prefixo único do próprio teste: outros testes (inclusive de
    # API, que commitam de verdade) também gravam na mesma tabela, então a
    # contagem só é exata se restrita aos registros que este teste criou.
    repositorio = MaterialRepositorySQLAlchemy(db_session)
    prefixo = str(uuid4())
    for i in range(3):
        await repositorio.adicionar(_material(titulo=f"Material {prefixo} {i}"))

    itens, total = await repositorio.listar(pagina=1, tamanho_pagina=2, titulo=prefixo)

    assert total == 3
    assert len(itens) == 2


async def test_listar_filtra_por_titulo_parcial(db_session: AsyncSession) -> None:
    repositorio = MaterialRepositorySQLAlchemy(db_session)
    prefixo = str(uuid4())
    await repositorio.adicionar(_material(titulo=f"Introdução a Grafos {prefixo}"))
    await repositorio.adicionar(_material(titulo=f"Árvores Binárias {prefixo}"))

    itens, total = await repositorio.listar(pagina=1, tamanho_pagina=20, titulo=f"grafos {prefixo}")

    assert total == 1
    assert itens[0].titulo == f"Introdução a Grafos {prefixo}"
