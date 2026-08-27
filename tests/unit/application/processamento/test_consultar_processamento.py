from datetime import UTC, datetime
from uuid import uuid4

import pytest

from application.processamento.consultar_processamento import ConsultarProcessamentoUseCase
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from domain.shared.exceptions import RecursoNaoEncontradoError

from .fakes import ProcessamentoRepositorioFake


def _processamento() -> Processamento:
    return Processamento(
        id=uuid4(),
        aluno_id=uuid4(),
        material_didatico_id=uuid4(),
        perfil_id=uuid4(),
        status=StatusProcessamento.PENDENTE,
        modelo_ia=None,
        data_criacao=datetime.now(UTC),
        inicio=None,
        fim=None,
        erro=None,
    )


async def test_retorna_processamento_existente() -> None:
    processamento = _processamento()
    processamentos = ProcessamentoRepositorioFake()
    processamentos.semear(processamento)

    resultado = await ConsultarProcessamentoUseCase(processamentos).executar(processamento.id)

    assert resultado.id == processamento.id


async def test_processamento_inexistente_levanta_recurso_nao_encontrado() -> None:
    processamentos = ProcessamentoRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await ConsultarProcessamentoUseCase(processamentos).executar(uuid4())

    assert excinfo.value.code == "PROCESSAMENTO_NAO_ENCONTRADO"
