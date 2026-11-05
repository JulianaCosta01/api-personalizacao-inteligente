import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from functools import lru_cache
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from application.ports.gerador_imagens import IGeradorDeImagens
from application.processamento.politica_de_repeticao import PoliticaDeRepeticao
from application.processamento.processar_personalizacao import (
    PosseDoProcessamentoPerdidaError,
    ProcessarPersonalizacaoUseCase,
)
from core.config import get_settings
from core.logging import configurar_logging, request_id_var
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
from infrastructure.imagens.cloudflare_adapter import CloudflareImageAdapter
from infrastructure.llm.cliente import get_gemini_client
from infrastructure.llm.gemini_adapter import GeminiAdapter
from infrastructure.queue.fila_postgres import FilaPostgres
from infrastructure.storage.cliente import get_storage_client
from infrastructure.storage.supabase_storage import SupabaseStorageAdapter
from worker.claim import reivindicar_processamento
from worker.loop import executar_loop

logger = logging.getLogger(__name__)


@lru_cache
def _obter_gerador_de_imagens() -> IGeradorDeImagens:
    """Gerador de imagens do processo, criado no primeiro uso.

    Um só por processo, para reaproveitar o cliente HTTP entre os jobs.
    """
    return CloudflareImageAdapter.a_partir_de_settings(get_settings())


def _construir_caso_de_uso(session: AsyncSession) -> ProcessarPersonalizacaoUseCase:
    settings = get_settings()
    # Desligado (padrão): nenhum gerador, e o GeminiAdapter segue exatamente como antes.
    gerador_de_imagens = (
        _obter_gerador_de_imagens() if settings.imagens_geradas_habilitadas else None
    )
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
            # Orçamento maior que uma tentativa única: o Worker não bloqueia requisição HTTP,
            # então pode esperar as tentativas de retry do SDK até o limite configurado.
            settings.gemini_timeout_total_segundos,
            imagens_geradas_habilitadas=settings.imagens_geradas_habilitadas,
            imagens_max_por_material=settings.imagens_max_por_material,
            gerador_de_imagens=gerador_de_imagens,
            imagens_orcamento_total_segundos=settings.imagens_orcamento_total_segundos,
            imagens_timeout_total_segundos=settings.imagens_timeout_total_segundos,
            timeout_extracao_segundos=settings.pipeline_timeout_extracao_segundos,
            timeout_pdf_segundos=settings.pipeline_timeout_pdf_segundos,
            reescrita_complemento_tentativas=settings.gemini_reescrita_complemento_tentativas,
            reescrita_proporcao_minima=settings.gemini_reescrita_proporcao_minima,
            anexar_imagens_originais=settings.pdf_anexar_imagens_originais,
        ),
        # Falha transitória do Gemini devolve o job à fila (com espera) até o limite de
        # reivindicações; o resto continua encerrando em erro.
        PoliticaDeRepeticao(
            settings.worker_tentativas_maximas,
            settings.worker_repeticao_atraso_base_segundos,
            settings.worker_repeticao_atraso_maximo_segundos,
        ),
    )


async def processar_reivindicado(
    processamento_id: UUID,
    fabrica_caso_de_uso: Callable[
        [AsyncSession], ProcessarPersonalizacaoUseCase
    ] = _construir_caso_de_uso,
) -> StatusProcessamento:
    """Executa a personalização de um Processamento já reivindicado.

    Use Case e remoção da fila commitam juntos. Se a remoção falhar, o upload já feito no
    Storage é revertido aqui, porque ele não entra na transação do banco.
    """
    prazo = get_settings().worker_prazo_maximo_job_segundos
    caso_de_uso: ProcessarPersonalizacaoUseCase | None = None
    try:
        async with sessao_transacional() as session:
            caso_de_uso = fabrica_caso_de_uso(session)
            # CancelledError (encerramento do Worker) não é capturado: segue propagando.
            resultado = await asyncio.wait_for(
                caso_de_uso.executar(processamento_id), timeout=prazo
            )

            # Só CONCLUIDO remove a mensagem. PENDENTE (devolvido por falha transitória) PRECISA
            # mantê-la: o claim parte da mensagem + status pendente. ERRO mantém, como antes.
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
    except (TimeoutError, asyncio.TimeoutError):  # noqa: UP041 - distintos antes do Python 3.11
        # A transação do job foi desfeita; o que ele gravou fora do banco (PDF) é revertido e o
        # processamento termina em erro, em vez de ficar preso até a recuperação.
        logger.error("Processamento %s excedeu o prazo de %.0f s.", processamento_id, prazo)
        if caso_de_uso is not None and caso_de_uso.chave_pdf_gerada is not None:
            await caso_de_uso.reverter_upload(caso_de_uso.chave_pdf_gerada)
        await encerrar_por_prazo_excedido(processamento_id)
        return StatusProcessamento.ERRO
    except PosseDoProcessamentoPerdidaError:
        logger.warning(
            "Processamento %s não foi gravado: outra execução assumiu a posse.", processamento_id
        )
        return StatusProcessamento.EM_PROCESSAMENTO

    logger.info("Processamento %s finalizado com status %s.", processamento_id, resultado.status)
    return resultado.status


async def encerrar_por_prazo_excedido(processamento_id: UUID) -> bool:
    """Marca como erro o job que estourou o prazo, em transação própria e só se ele ainda estiver
    em_processamento (nunca sobrescreve um estado já decidido)."""
    async with sessao_transacional() as session:
        repositorio = ProcessamentoRepositorySQLAlchemy(session)
        processamento = await repositorio.obter_por_id(processamento_id)
        if processamento is None or processamento.status != StatusProcessamento.EM_PROCESSAMENTO:
            return False
        processamento.marcar_como_erro("O processamento excedeu o prazo máximo.")
        return await repositorio.atualizar_se_dono(processamento)


async def recuperar_processamentos_presos() -> list[UUID]:
    """Devolve para pendente Processamentos presos em em_processamento além do tempo
    configurado. Chamada na inicialização e periodicamente durante o loop (ver
    _construir_ciclo_com_recuperacao_periodica). A mensagem na fila permanece intacta
    durante todo o ciclo, então o Processamento liberado vira candidato válido de claim
    sem republicação.
    """
    settings = get_settings()
    idade_maxima = timedelta(seconds=settings.worker_idade_maxima_presos_segundos)

    async with sessao_transacional() as session:
        repositorio = ProcessamentoRepositorySQLAlchemy(session)
        # Primeiro encerra quem já esgotou as tentativas; só então devolve os demais à fila.
        esgotados = await repositorio.esgotar_tentativas_dos_presos(
            idade_maxima, settings.worker_tentativas_maximas
        )
        liberados = await repositorio.liberar_presos(
            idade_maxima, settings.worker_tentativas_maximas
        )

    if esgotados:
        logger.error(
            "%d processamento(s) preso(s) encerrado(s) em erro por excesso de tentativas: %s",
            len(esgotados),
            esgotados,
        )

    if liberados:
        logger.warning(
            "%d processamento(s) preso(s) devolvido(s) para pendente: %s",
            len(liberados),
            liberados,
        )
    return liberados


async def executar_ciclo() -> None:
    """Reivindica um Processamento pendente e, se houver, executa a personalização.

    processamento_id vira o id de correlação dos logs; o reset no finally evita que ele vaze
    para o próximo ciclo.
    """
    processamento_id = await reivindicar_processamento()
    if processamento_id is None:
        return

    token = request_id_var.set(str(processamento_id))
    try:
        await processar_reivindicado(processamento_id)
    finally:
        request_id_var.reset(token)


def _construir_ciclo_com_recuperacao_periodica(
    intervalo_recuperacao_segundos: float,
) -> Callable[[], Awaitable[None]]:
    """Envolve executar_ciclo para rodar também a recuperação de processamentos presos.

    Roda antes do ciclo normal quando o intervalo vence, sem substituir nenhuma iteração.
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
    # Sem isso o processo Worker fica com o logging padrão do Python (nível WARNING, texto
    # puro): os INFO de claim e conclusão somem e nada sai em JSON com a correlação.
    configurar_logging(settings.log_level)
    # Sem esta linha, um Worker ocioso não escreve nada e fica indistinguível de um Worker sem
    # logging. Só valores não secretos.
    logger.info(
        "Worker iniciado: tentativas máximas=%d, polling=%.0f s, prazo por job=%.0f s.",
        settings.worker_tentativas_maximas,
        settings.worker_intervalo_polling_segundos,
        settings.worker_prazo_maximo_job_segundos,
    )
    await recuperar_processamentos_presos()
    ciclo = _construir_ciclo_com_recuperacao_periodica(settings.worker_idade_maxima_presos_segundos)
    await executar_loop(settings.worker_intervalo_polling_segundos, ciclo)


if __name__ == "__main__":
    asyncio.run(executar_worker())
