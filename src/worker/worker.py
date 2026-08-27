import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from application.processamento.processar_personalizacao import ProcessarPersonalizacaoUseCase
from core.config import get_settings
from domain.processamento.status_processamento import StatusProcessamento
from infrastructure.database.material.material_repository import MaterialRepositorySQLAlchemy
from infrastructure.database.material_personalizado.material_personalizado_repository import (
    MaterialPersonalizadoRepositorySQLAlchemy,
)
from infrastructure.database.perfil.perfil_repository import PerfilRepositorySQLAlchemy
from infrastructure.database.processamento.processamento_repository import (
    ProcessamentoRepositorySQLAlchemy,
)
from infrastructure.database.session import sessao_transacional
from infrastructure.llm.cliente import get_gemini_client
from infrastructure.llm.gemini_adapter import GeminiAdapter
from infrastructure.queue.fila_postgres import FilaPostgres
from infrastructure.storage.cliente import get_storage_client
from infrastructure.storage.supabase_storage import SupabaseStorageAdapter
from worker.claim import reivindicar_processamento
from worker.loop import executar_loop

logger = logging.getLogger(__name__)


def _construir_caso_de_uso(session: AsyncSession) -> ProcessarPersonalizacaoUseCase:
    settings = get_settings()
    return ProcessarPersonalizacaoUseCase(
        ProcessamentoRepositorySQLAlchemy(session),
        MaterialRepositorySQLAlchemy(session),
        PerfilRepositorySQLAlchemy(session),
        MaterialPersonalizadoRepositorySQLAlchemy(session),
        SupabaseStorageAdapter(get_storage_client(), settings.storage_bucket_materiais),
        GeminiAdapter(
            get_gemini_client(),
            settings.gemini_model,
            settings.gemini_timeout_segundos,
            # Orçamento maior que uma tentativa única: o Worker não bloqueia
            # nenhuma requisição HTTP, então pode esperar as tentativas de
            # retry do SDK (Fase 8 Task 6) até o limite configurado.
            settings.gemini_timeout_total_segundos,
        ),
    )


async def processar_reivindicado(
    processamento_id: UUID,
    fabrica_caso_de_uso: Callable[
        [AsyncSession], ProcessarPersonalizacaoUseCase
    ] = _construir_caso_de_uso,
) -> StatusProcessamento:
    """Executa a personalização de um Processamento já reivindicado (claim.py).

    Transação própria: o Use Case (via seus repositórios) e a remoção da
    mensagem da fila em caso de sucesso commitam juntos, como uma unidade.
    `fabrica_caso_de_uso` existe para permitir injetar Storage/LLM fakes nos
    testes, sem tocar rede real — por padrão monta os adaptadores concretos.

    Se a remoção da mensagem da fila falhar DEPOIS do Use Case ter concluído
    com sucesso, toda a transação é desfeita (MaterialPersonalizado e o status
    concluído voltam atrás) — mas o PDF já enviado ao Storage não é desfeito
    junto, por não ser transacional com o banco. Por isso o upload é revertido
    explicitamente aqui antes de propagar o erro original.
    """
    async with sessao_transacional() as session:
        caso_de_uso = fabrica_caso_de_uso(session)
        resultado = await caso_de_uso.executar(processamento_id)

        if resultado.status == StatusProcessamento.CONCLUIDO:
            try:
                await FilaPostgres(session).remover(processamento_id)
            except Exception:
                logger.exception(
                    "Falha ao remover processamento %s da fila; revertendo upload do PDF.",
                    processamento_id,
                )
                if caso_de_uso.chave_pdf_gerada is not None:
                    await caso_de_uso.reverter_upload(caso_de_uso.chave_pdf_gerada)
                raise

    logger.info("Processamento %s finalizado com status %s.", processamento_id, resultado.status)
    return resultado.status


async def recuperar_processamentos_presos() -> list[UUID]:
    """Devolve para pendente Processamentos presos em em_processamento havia
    mais tempo que o configurado. Chamada tanto na inicialização do Worker
    quanto periodicamente durante o loop contínuo (ver
    _construir_ciclo_com_recuperacao_periodica). A mensagem na
    fila_processamento permanece intacta durante todo o ciclo (só é removida
    em caso de sucesso), então o Processamento liberado volta a ser um
    candidato válido de claim sem republicação.
    """
    settings = get_settings()
    idade_maxima = timedelta(seconds=settings.worker_idade_maxima_presos_segundos)

    async with sessao_transacional() as session:
        liberados = await ProcessamentoRepositorySQLAlchemy(session).liberar_presos(idade_maxima)

    if liberados:
        logger.warning(
            "%d processamento(s) preso(s) devolvido(s) para pendente: %s",
            len(liberados),
            liberados,
        )
    return liberados


async def executar_ciclo() -> None:
    """Uma iteração do loop: reivindica um Processamento pendente e, se
    conseguir, executa a personalização. Sem trabalho pendente, não faz nada —
    a espera entre tentativas é responsabilidade exclusiva do loop."""
    processamento_id = await reivindicar_processamento()
    if processamento_id is None:
        return
    await processar_reivindicado(processamento_id)


def _construir_ciclo_com_recuperacao_periodica(
    intervalo_recuperacao_segundos: float,
) -> Callable[[], Awaitable[None]]:
    """Envolve executar_ciclo para também rodar recuperar_processamentos_presos
    periodicamente, sem introduzir nenhum scheduler externo: o loop genérico
    de polling (executar_loop) continua sendo o único responsável por disparar
    as iterações, no intervalo normal (worker_intervalo_polling_segundos, não
    afetado por esta função). A cada iteração, esta função apenas verifica se
    já se passou intervalo_recuperacao_segundos desde a última recuperação; se
    sim, roda a recuperação antes do ciclo normal de claim/processamento. Uma
    recuperação atrasada nunca substitui uma iteração de claim — ela só
    acontece a mais, quando devida.
    """
    ultima_execucao = time.monotonic()

    async def _ciclo() -> None:
        nonlocal ultima_execucao
        agora = time.monotonic()
        if agora - ultima_execucao >= intervalo_recuperacao_segundos:
            ultima_execucao = agora
            await recuperar_processamentos_presos()
        await executar_ciclo()

    return _ciclo


async def executar_worker() -> None:
    """Ponto de entrada do processo Worker: recupera processamentos presos na
    inicialização e então inicia o loop contínuo de polling, que passa a
    repetir essa mesma recuperação periodicamente (a cada
    worker_idade_maxima_presos_segundos) enquanto o Worker estiver vivo."""
    settings = get_settings()
    await recuperar_processamentos_presos()
    ciclo = _construir_ciclo_com_recuperacao_periodica(settings.worker_idade_maxima_presos_segundos)
    await executar_loop(settings.worker_intervalo_polling_segundos, ciclo)


if __name__ == "__main__":
    asyncio.run(executar_worker())
