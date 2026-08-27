from datetime import UTC, datetime
from uuid import uuid4

import pytest

from application.material_personalizado.consultar_material_personalizado import (
    ConsultarMaterialPersonalizadoUseCase,
)
from domain.material_personalizado.material_personalizado import MaterialPersonalizado
from domain.shared.exceptions import RecursoNaoEncontradoError
from tests.unit.application.processamento.fakes import MaterialPersonalizadoRepositorioFake


def _material() -> MaterialPersonalizado:
    return MaterialPersonalizado(
        id=uuid4(),
        processamento_id=uuid4(),
        titulo="Título Personalizado",
        caminho_pdf="materiais-personalizados/x.pdf",
        resumo="Resumo do material.",
        data_geracao=datetime.now(UTC),
    )


async def test_retorna_material_existente() -> None:
    material = _material()
    materiais = MaterialPersonalizadoRepositorioFake()
    await materiais.adicionar(material)

    resultado = await ConsultarMaterialPersonalizadoUseCase(materiais).executar(material.id)

    assert resultado.id == material.id


async def test_material_inexistente_levanta_recurso_nao_encontrado() -> None:
    materiais = MaterialPersonalizadoRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await ConsultarMaterialPersonalizadoUseCase(materiais).executar(uuid4())

    assert excinfo.value.code == "MATERIAL_PERSONALIZADO_NAO_ENCONTRADO"
