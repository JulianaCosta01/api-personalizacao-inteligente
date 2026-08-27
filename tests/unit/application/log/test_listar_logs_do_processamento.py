from datetime import UTC, datetime
from uuid import uuid4

import pytest

from application.log.listar_logs_do_processamento import (
    ListarLogsDoProcessamentoInput,
    ListarLogsDoProcessamentoUseCase,
)
from domain.log.log_interacao import LogInteracao
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from domain.shared.exceptions import RecursoNaoEncontradoError
from tests.unit.application.log.fakes import LogRepositorioFake
from tests.unit.application.processamento.fakes import ProcessamentoRepositorioFake


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


def _log(processamento_id: object, timestamp: datetime) -> LogInteracao:
    return LogInteracao(
        id=uuid4(),
        aluno_id=uuid4(),
        processamento_id=processamento_id,  # type: ignore[arg-type]
        acao="leitura_material_personalizado",
        descricao=None,
        timestamp=timestamp,
    )


async def test_lista_logs_do_processamento_ordenados_por_timestamp_crescente() -> None:
    processamento = _processamento()
    processamentos = ProcessamentoRepositorioFake()
    processamentos.semear(processamento)

    logs = LogRepositorioFake()
    logs.semear(_log(processamento.id, datetime(2026, 1, 2, tzinfo=UTC)))
    logs.semear(_log(processamento.id, datetime(2026, 1, 1, tzinfo=UTC)))
    logs.semear(_log(uuid4(), datetime(2026, 1, 1, tzinfo=UTC)))  # de outro processamento

    resultado = await ListarLogsDoProcessamentoUseCase(processamentos, logs).executar(
        ListarLogsDoProcessamentoInput(processamento_id=processamento.id)
    )

    assert resultado.total_itens == 2
    assert resultado.itens[0].timestamp < resultado.itens[1].timestamp


async def test_processamento_inexistente_levanta_recurso_nao_encontrado() -> None:
    processamentos = ProcessamentoRepositorioFake()
    logs = LogRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await ListarLogsDoProcessamentoUseCase(processamentos, logs).executar(
            ListarLogsDoProcessamentoInput(processamento_id=uuid4())
        )

    assert excinfo.value.code == "PROCESSAMENTO_NAO_ENCONTRADO"


async def test_pagina_vazia_quando_nao_ha_logs() -> None:
    processamento = _processamento()
    processamentos = ProcessamentoRepositorioFake()
    processamentos.semear(processamento)
    logs = LogRepositorioFake()

    resultado = await ListarLogsDoProcessamentoUseCase(processamentos, logs).executar(
        ListarLogsDoProcessamentoInput(processamento_id=processamento.id)
    )

    assert resultado.itens == []
    assert resultado.total_itens == 0
