from datetime import UTC, datetime
from uuid import uuid4

import pytest

from application.material_personalizado.consultar_material_personalizado_do_processamento import (
    ConsultarMaterialPersonalizadoDoProcessamentoUseCase,
)
from domain.material_personalizado.material_personalizado import MaterialPersonalizado
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from domain.shared.exceptions import ConflitoDeEstadoError, RecursoNaoEncontradoError
from tests.unit.application.processamento.fakes import (
    MaterialPersonalizadoRepositorioFake,
    ProcessamentoRepositorioFake,
)


def _processamento(status: StatusProcessamento) -> Processamento:
    return Processamento(
        id=uuid4(),
        aluno_id=uuid4(),
        material_didatico_id=uuid4(),
        perfil_id=uuid4(),
        status=status,
        modelo_ia="gemini-2.0-flash" if status != StatusProcessamento.PENDENTE else None,
        data_criacao=datetime.now(UTC),
        inicio=None,
        fim=None,
        erro=None,
    )


def _material(processamento_id: object) -> MaterialPersonalizado:
    return MaterialPersonalizado(
        id=uuid4(),
        processamento_id=processamento_id,  # type: ignore[arg-type]
        titulo="Título Personalizado",
        caminho_pdf="materiais-personalizados/x.pdf",
        resumo="Resumo do material.",
        data_geracao=datetime.now(UTC),
    )


async def test_retorna_material_quando_processamento_concluido() -> None:
    processamento = _processamento(StatusProcessamento.CONCLUIDO)
    processamentos = ProcessamentoRepositorioFake()
    processamentos.semear(processamento)
    material = _material(processamento.id)
    materiais = MaterialPersonalizadoRepositorioFake()
    await materiais.adicionar(material)

    resultado = await ConsultarMaterialPersonalizadoDoProcessamentoUseCase(
        processamentos, materiais
    ).executar(processamento.id)

    assert resultado.id == material.id


async def test_processamento_inexistente_levanta_recurso_nao_encontrado() -> None:
    processamentos = ProcessamentoRepositorioFake()
    materiais = MaterialPersonalizadoRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await ConsultarMaterialPersonalizadoDoProcessamentoUseCase(
            processamentos, materiais
        ).executar(uuid4())

    assert excinfo.value.code == "PROCESSAMENTO_NAO_ENCONTRADO"


@pytest.mark.parametrize(
    "status",
    [StatusProcessamento.PENDENTE, StatusProcessamento.EM_PROCESSAMENTO, StatusProcessamento.ERRO],
)
async def test_processamento_nao_concluido_levanta_conflito_de_estado(
    status: StatusProcessamento,
) -> None:
    processamento = _processamento(status)
    processamentos = ProcessamentoRepositorioFake()
    processamentos.semear(processamento)
    materiais = MaterialPersonalizadoRepositorioFake()

    with pytest.raises(ConflitoDeEstadoError) as excinfo:
        await ConsultarMaterialPersonalizadoDoProcessamentoUseCase(
            processamentos, materiais
        ).executar(processamento.id)

    assert excinfo.value.code == "MATERIAL_PERSONALIZADO_INDISPONIVEL"
    assert excinfo.value.details is not None
    assert excinfo.value.details["status"] == status.value


async def test_processamento_concluido_sem_material_levanta_conflito_de_estado(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Cenário defensivo: não deveria ocorrer em uso normal (Worker sempre grava
    # o material antes de marcar concluido), mas o use case precisa tratar.
    processamento = _processamento(StatusProcessamento.CONCLUIDO)
    processamentos = ProcessamentoRepositorioFake()
    processamentos.semear(processamento)
    materiais = MaterialPersonalizadoRepositorioFake()

    with caplog.at_level("WARNING"), pytest.raises(ConflitoDeEstadoError) as excinfo:
        await ConsultarMaterialPersonalizadoDoProcessamentoUseCase(
            processamentos, materiais
        ).executar(processamento.id)

    assert excinfo.value.code == "MATERIAL_PERSONALIZADO_INDISPONIVEL"
    assert any(r.levelname == "WARNING" for r in caplog.records)
    assert str(processamento.id) in caplog.text
