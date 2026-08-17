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
