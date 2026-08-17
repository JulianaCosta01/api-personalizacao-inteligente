from unittest.mock import AsyncMock, patch
from uuid import uuid4

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
