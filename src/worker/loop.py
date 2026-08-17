import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


async def executar_loop(intervalo_segundos: float, ciclo: Callable[[], Awaitable[None]]) -> None:
    """Loop contínuo de polling, sem busy waiting: cada iteração espera o
    intervalo configurado antes da próxima tentativa. CancelledError propaga
    para permitir encerramento limpo; qualquer outra exceção de um ciclo é
    registrada e o loop continua — uma falha isolada não derruba o Worker."""
    while True:
        try:
            await ciclo()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha não tratada em um ciclo do Worker.")
        await asyncio.sleep(intervalo_segundos)
