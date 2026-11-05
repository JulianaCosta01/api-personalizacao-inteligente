import logging
from uuid import UUID

from infrastructure.database.session import sessao_transacional
from infrastructure.queue.fila_postgres import FilaPostgres

logger = logging.getLogger(__name__)


async def reivindicar_processamento() -> UUID | None:
    """Tenta reivindicar o próximo Processamento pendente da fila.

    Transação própria e curta: o claim commita imediatamente, independente do
    tempo que a execução (chamada LLM, geração de PDF) levar depois: evita
    segurar lock/transação aberta pela duração inteira do processamento.
    """
    async with sessao_transacional() as session:
        fila = FilaPostgres(session)
        processamento_id = await fila.reivindicar_proximo()

    if processamento_id is not None:
        logger.info("Processamento %s reivindicado.", processamento_id)
    return processamento_id
