import asyncio
import logging
from collections.abc import Awaitable, Callable

from worker.heartbeat import atualizar_heartbeat

logger = logging.getLogger(__name__)


async def executar_loop(intervalo_segundos: float, ciclo: Callable[[], Awaitable[None]]) -> None:
    """Loop contínuo de polling, sem busy waiting: cada iteração espera o
    intervalo configurado antes da próxima tentativa. CancelledError propaga
    para permitir encerramento limpo; qualquer outra exceção de um ciclo é
    registrada e o loop continua — uma falha isolada não derruba o Worker.

    Fase 11 — heartbeat atualizado ao final de toda iteração (sucesso ou
    falha capturada), não só quando há trabalho: prova que o loop em si
    segue vivo e ciclando, distinto de "o último job deu certo".
    """
    while True:
        try:
            await ciclo()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha não tratada em um ciclo do Worker.")
        atualizar_heartbeat()
        await asyncio.sleep(intervalo_segundos)
