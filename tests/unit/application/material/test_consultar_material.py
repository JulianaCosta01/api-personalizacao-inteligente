from datetime import UTC, datetime
from uuid import uuid4

import pytest

from application.material.consultar_material import ConsultarMaterialUseCase
from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo
from domain.shared.exceptions import RecursoNaoEncontradoError

from .fakes import MaterialRepositorioFake


def _material() -> MaterialDidatico:
    return MaterialDidatico(
        id=uuid4(),
        titulo="Introdução a Grafos",
        nome_arquivo="grafos.pdf",
        tipo_arquivo=TipoArquivo.PDF,
        caminho_storage="materiais/grafos.pdf",
        versao=1,
        data_upload=datetime.now(UTC),
    )


async def test_retorna_material_quando_encontrado() -> None:
    repositorio = MaterialRepositorioFake()
    material = _material()
    repositorio.semear(material)

    resultado = await ConsultarMaterialUseCase(repositorio).executar(material.id)

    assert resultado == material


async def test_levanta_recurso_nao_encontrado_quando_id_nao_existe() -> None:
    repositorio = MaterialRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError):
        await ConsultarMaterialUseCase(repositorio).executar(uuid4())
