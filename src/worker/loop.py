import asyncio
import logging
from collections.abc import Awaitable, Callable

from worker.heartbeat import atualizar_heartbeat

logger = logging.getLogger(__name__)


async def executar_loop(intervalo_segundos: float, ciclo: Callable[[], Awaitable[None]]) -> None:
    """Loop contínuo de polling, sem busy waiting: espera o intervalo configurado entre
    tentativas. CancelledError propaga para encerramento limpo; qualquer outra exceção é
    registrada e o loop continua. Heartbeat atualizado ao final de toda iteração (sucesso
    ou falha), não só quando há trabalho — prova que o loop segue vivo, distinto de "o
    último job deu certo".
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
