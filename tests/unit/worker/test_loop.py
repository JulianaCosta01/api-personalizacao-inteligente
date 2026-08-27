import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from worker.loop import executar_loop


async def test_executa_o_ciclo_repetidamente() -> None:
    chamadas = 0

    async def ciclo() -> None:
        nonlocal chamadas
        chamadas += 1
        if chamadas >= 3:
            raise asyncio.CancelledError

    with patch("asyncio.sleep", new=AsyncMock()), pytest.raises(asyncio.CancelledError):
        await executar_loop(0.01, ciclo)

    assert chamadas == 3


async def test_respeita_o_intervalo_configurado_entre_ciclos() -> None:
    chamadas = 0

    async def ciclo() -> None:
        nonlocal chamadas
        chamadas += 1
        if chamadas >= 2:
            raise asyncio.CancelledError

    with (
        patch("asyncio.sleep", new=AsyncMock()) as sleep_mock,
        pytest.raises(asyncio.CancelledError),
    ):
        await executar_loop(2.5, ciclo)

    sleep_mock.assert_awaited_with(2.5)


async def test_cancelamento_via_task_encerra_o_loop_de_forma_limpa() -> None:
    chamadas = 0
    liberar = asyncio.Event()

    async def ciclo() -> None:
        nonlocal chamadas
        chamadas += 1
        liberar.set()

    tarefa = asyncio.create_task(executar_loop(0.01, ciclo))
    await asyncio.wait_for(liberar.wait(), timeout=2)
    tarefa.cancel()

    with pytest.raises(asyncio.CancelledError):
        await tarefa

    assert chamadas >= 1


async def test_excecao_de_um_ciclo_nao_interrompe_o_loop() -> None:
    chamadas = 0

    async def ciclo() -> None:
        nonlocal chamadas
        chamadas += 1
        if chamadas == 1:
            raise RuntimeError("falha simulada de processamento")
        raise asyncio.CancelledError

    with patch("asyncio.sleep", new=AsyncMock()), pytest.raises(asyncio.CancelledError):
        await executar_loop(0.01, ciclo)

    assert chamadas == 2


async def test_atualiza_o_heartbeat_a_cada_iteracao() -> None:
    # A 3ª chamada lança CancelledError, que é relançada imediatamente por
    # executar_loop (antes de atualizar_heartbeat) para permitir cancelamento
    # limpo — por isso só as 2 iterações que completam normalmente contam.
    chamadas = 0

    async def ciclo() -> None:
        nonlocal chamadas
        chamadas += 1
        if chamadas >= 3:
            raise asyncio.CancelledError

    with (
        patch("asyncio.sleep", new=AsyncMock()),
        patch("worker.loop.atualizar_heartbeat") as heartbeat_mock,
        pytest.raises(asyncio.CancelledError),
    ):
        await executar_loop(0.01, ciclo)

    assert heartbeat_mock.call_count == 2


async def test_atualiza_o_heartbeat_mesmo_quando_um_ciclo_lanca_excecao() -> None:
    # Heartbeat prova que o LOOP está vivo, não que o último job deu certo —
    # por isso precisa ser chamado mesmo quando o ciclo falha (a exceção já é
    # capturada e logada dentro de executar_loop, sem interromper o loop). A
    # 2ª chamada lança CancelledError, relançada antes de atualizar_heartbeat
    # (mesmo motivo do teste acima) — por isso só a 1ª iteração conta.
    chamadas = 0

    async def ciclo() -> None:
        nonlocal chamadas
        chamadas += 1
        if chamadas == 1:
            raise RuntimeError("falha simulada de processamento")
        raise asyncio.CancelledError

    with (
        patch("asyncio.sleep", new=AsyncMock()),
        patch("worker.loop.atualizar_heartbeat") as heartbeat_mock,
        pytest.raises(asyncio.CancelledError),
    ):
        await executar_loop(0.01, ciclo)

    assert heartbeat_mock.call_count == 1
