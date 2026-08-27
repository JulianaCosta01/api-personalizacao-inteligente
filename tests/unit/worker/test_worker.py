import json
import logging
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from core.logging import JsonFormatter, request_id_var
from worker.worker import _construir_ciclo_com_recuperacao_periodica, executar_ciclo


async def test_ciclo_nao_processa_quando_nao_ha_nada_para_reivindicar() -> None:
    with (
        patch("worker.worker.reivindicar_processamento", new=AsyncMock(return_value=None)),
        patch("worker.worker.processar_reivindicado", new=AsyncMock()) as processar_mock,
    ):
        await executar_ciclo()

    processar_mock.assert_not_awaited()


async def test_ciclo_processa_o_processamento_reivindicado() -> None:
    processamento_id = uuid4()
    with (
        patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=processamento_id),
        ),
        patch("worker.worker.processar_reivindicado", new=AsyncMock()) as processar_mock,
    ):
        await executar_ciclo()

    processar_mock.assert_awaited_once_with(processamento_id)


async def test_ciclo_com_recuperacao_periodica_nao_recupera_antes_do_intervalo() -> None:
    # Fase 7, Etapa 6 — Item 2: logo após construído (equivalente a logo após
    # a recuperação já feita na inicialização do Worker), nenhuma chamada
    # deveria dever recuperação — o intervalo configurado ainda não passou.
    with (
        patch("worker.worker.reivindicar_processamento", new=AsyncMock(return_value=None)),
        patch("worker.worker.recuperar_processamentos_presos", new=AsyncMock()) as recuperar_mock,
    ):
        ciclo = _construir_ciclo_com_recuperacao_periodica(600.0)
        await ciclo()
        await ciclo()
        await ciclo()

    recuperar_mock.assert_not_awaited()


async def test_ciclo_com_recuperacao_periodica_dispara_apos_intervalo_decorrido() -> None:
    # Com intervalo 0.0, toda iteração já está "vencida" — prova que a
    # recuperação periódica de fato dispara quando o tempo configurado passa,
    # sem depender de nenhum scheduler externo.
    with (
        patch("worker.worker.reivindicar_processamento", new=AsyncMock(return_value=None)),
        patch("worker.worker.recuperar_processamentos_presos", new=AsyncMock()) as recuperar_mock,
    ):
        ciclo = _construir_ciclo_com_recuperacao_periodica(0.0)
        await ciclo()
        await ciclo()
        await ciclo()

    assert recuperar_mock.await_count == 3


async def test_ciclo_com_recuperacao_periodica_nao_interfere_no_polling_normal() -> None:
    # A recuperação periódica é uma etapa A MAIS dentro do ciclo, nunca no
    # lugar do claim/processamento normal: reivindicar_processamento e
    # processar_reivindicado continuam sendo chamados em toda iteração,
    # esteja ou não a recuperação também devida naquela iteração.
    processamento_id = uuid4()
    with (
        patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=processamento_id),
        ),
        patch("worker.worker.processar_reivindicado", new=AsyncMock()) as processar_mock,
        patch("worker.worker.recuperar_processamentos_presos", new=AsyncMock()) as recuperar_mock,
    ):
        ciclo = _construir_ciclo_com_recuperacao_periodica(0.0)
        await ciclo()
        await ciclo()

    assert processar_mock.await_count == 2
    assert recuperar_mock.await_count == 2


async def test_ciclo_define_request_id_var_com_processamento_id_durante_o_processamento() -> None:
    processamento_id = uuid4()
    capturado: list[str | None] = []

    async def _processar_capturando_contexto(_id: object) -> None:
        capturado.append(request_id_var.get())

    with (
        patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=processamento_id),
        ),
        patch(
            "worker.worker.processar_reivindicado",
            new=AsyncMock(side_effect=_processar_capturando_contexto),
        ),
    ):
        await executar_ciclo()

    assert capturado == [str(processamento_id)]


async def test_ciclo_restaura_o_contexto_apos_o_processamento() -> None:
    processamento_id = uuid4()

    with (
        patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=processamento_id),
        ),
        patch("worker.worker.processar_reivindicado", new=AsyncMock()),
    ):
        await executar_ciclo()

    assert request_id_var.get() is None


async def test_ciclo_restaura_o_contexto_mesmo_quando_processar_reivindicado_lanca_excecao() -> (
    None
):
    processamento_id = uuid4()

    with (
        patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=processamento_id),
        ),
        patch(
            "worker.worker.processar_reivindicado",
            new=AsyncMock(side_effect=RuntimeError("falha simulada no processamento")),
        ),
        pytest.raises(RuntimeError, match="falha simulada no processamento"),
    ):
        await executar_ciclo()

    assert request_id_var.get() is None


async def test_dois_processamentos_consecutivos_nao_compartilham_o_mesmo_request_id() -> None:
    primeiro_id = uuid4()
    segundo_id = uuid4()
    capturado: list[str | None] = []

    async def _processar_capturando_contexto(_id: object) -> None:
        capturado.append(request_id_var.get())

    with patch(
        "worker.worker.processar_reivindicado",
        new=AsyncMock(side_effect=_processar_capturando_contexto),
    ):
        with patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=primeiro_id),
        ):
            await executar_ciclo()

        # Nada de request_id vazado do primeiro ciclo antes do segundo começar.
        assert request_id_var.get() is None

        with patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=segundo_id),
        ):
            await executar_ciclo()

    assert capturado == [str(primeiro_id), str(segundo_id)]
    assert capturado[0] != capturado[1]


async def test_logs_emitidos_durante_o_processamento_carregam_o_mesmo_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Prova a integração real, não só o ContextVar isolado: um logger
    # arbitrário chamado durante o processamento (simulando
    # processar_personalizacao.py/gemini_adapter.py) é formatado pelo
    # JsonFormatter de verdade — sem nenhuma alteração em core/logging.py — e
    # o resultado carrega o processamento_id. A formatação precisa acontecer
    # DENTRO do contexto (enquanto request_id_var ainda está definido), por
    # isso é feita no próprio side_effect, não depois que executar_ciclo já
    # tiver restaurado o contexto.
    processamento_id = uuid4()
    logger_do_pipeline = logging.getLogger("worker.teste_pipeline")
    payloads_formatados: list[dict[str, str]] = []

    async def _processar_logando(_id: object) -> None:
        logger_do_pipeline.info("Processando material personalizado.")
        payloads_formatados.append(json.loads(JsonFormatter().format(caplog.records[-1])))

    with (
        caplog.at_level(logging.INFO, logger="worker.teste_pipeline"),
        patch(
            "worker.worker.reivindicar_processamento",
            new=AsyncMock(return_value=processamento_id),
        ),
        patch(
            "worker.worker.processar_reivindicado",
            new=AsyncMock(side_effect=_processar_logando),
        ),
    ):
        await executar_ciclo()

    assert len(payloads_formatados) == 1
    assert payloads_formatados[0]["request_id"] == str(processamento_id)
