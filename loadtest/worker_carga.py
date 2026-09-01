"""Worker de carga da Fase 10, Task 2 — mesmo consumidor da fila_processamento do Worker de
produção (src/worker/worker.py), com Storage e LLM substituídos pelos fakes de loadtest/fakes.py.
Nunca chama Gemini nem Supabase Storage reais.

Reaproveita sem alterar: worker.claim.reivindicar_processamento,
worker.worker.processar_reivindicado (já aceita `fabrica_caso_de_uso` injetável, ponto de
extensão criado na Fase 7 para permitir fakes nos testes),
worker.worker.recuperar_processamentos_presos, worker.loop.executar_loop e
core.logging.request_id_var.

A única coisa reimplementada aqui é o wrapper de correlação (set/reset de request_id_var), porque
`executar_ciclo` (worker/worker.py) não expõe `fabrica_caso_de_uso` como parâmetro — adicionar isso
mudaria a assinatura pública do Worker de produção sem necessidade fora do escopo desta Task.

Uso:
    PYTHONPATH=src uv run python -m loadtest.worker_carga --latencia-llm-segundos 2.0
"""

import argparse
import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from application.processamento.processar_personalizacao import ProcessarPersonalizacaoUseCase
from core.config import get_settings
from core.logging import configurar_logging, request_id_var
from infrastructure.database.material.material_repository import MaterialRepositorySQLAlchemy
from infrastructure.database.material_personalizado.material_personalizado_repository import (
    MaterialPersonalizadoRepositorySQLAlchemy,
)
from infrastructure.database.perfil.perfil_repository import PerfilRepositorySQLAlchemy
from infrastructure.database.processamento.processamento_repository import (
    ProcessamentoRepositorySQLAlchemy,
)
from loadtest.fakes import LLMFakeComLatencia, ObjectStorageFake
from worker.claim import reivindicar_processamento
from worker.loop import executar_loop
from worker.worker import processar_reivindicado, recuperar_processamentos_presos

logger = logging.getLogger(__name__)

FabricaCasoDeUso = Callable[[AsyncSession], ProcessarPersonalizacaoUseCase]


def _construir_fabrica_de_carga(latencia_llm_segundos: float) -> FabricaCasoDeUso:
    def _fabrica(session: AsyncSession) -> ProcessarPersonalizacaoUseCase:
        # Instância nova por chamada, mesma vida útil de um Processamento — sem estado
        # compartilhado entre execuções concorrentes (mesma razão do GeminiAdapter real).
        return ProcessarPersonalizacaoUseCase(
            ProcessamentoRepositorySQLAlchemy(session),
            MaterialRepositorySQLAlchemy(session),
            PerfilRepositorySQLAlchemy(session),
            MaterialPersonalizadoRepositorySQLAlchemy(session),
            ObjectStorageFake(),
            LLMFakeComLatencia(latencia_llm_segundos),
        )

    return _fabrica


async def _ciclo_de_carga(fabrica_caso_de_uso: FabricaCasoDeUso) -> None:
    """Espelha executar_ciclo (worker/worker.py, Fase 10 Task 1) — ver docstring do módulo
    sobre por que este wrapper precisa existir separadamente."""
    processamento_id = await reivindicar_processamento()
    if processamento_id is None:
        return

    token = request_id_var.set(str(processamento_id))
    try:
        await processar_reivindicado(processamento_id, fabrica_caso_de_uso)
    finally:
        request_id_var.reset(token)


async def _executar(latencia_llm_segundos: float, intervalo_polling_segundos: float) -> None:
    settings = get_settings()
    configurar_logging(settings.log_level)
    logger.warning(
        "Worker de CARGA iniciado (Fase 10 Task 2) — Storage e LLM são fakes "
        "(loadtest/fakes.py); nenhuma chamada real ao Gemini ou ao Supabase Storage será feita. "
        "latencia_llm_segundos=%s (PROPOSTA, ver loadtest/README.md).",
        latencia_llm_segundos,
    )
    await recuperar_processamentos_presos()
    fabrica = _construir_fabrica_de_carga(latencia_llm_segundos)

    async def _ciclo() -> None:
        await _ciclo_de_carga(fabrica)

    await executar_loop(intervalo_polling_segundos, _ciclo)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Worker de carga da Fase 10, Task 2 — usa fakes de LLM/Storage, nunca "
        "toca Gemini ou Supabase reais."
    )
    parser.add_argument(
        "--latencia-llm-segundos",
        type=float,
        default=2.0,
        help="PROPOSTA: latência artificial simulando o tempo de resposta do Gemini "
        "(default não é um valor medido — ver loadtest/README.md).",
    )
    parser.add_argument(
        "--intervalo-polling-segundos",
        type=float,
        default=None,
        help="Default: WORKER_INTERVALO_POLLING_SEGUNDOS do .env (mesmo do Worker de produção).",
    )
    args = parser.parse_args()

    intervalo = args.intervalo_polling_segundos
    if intervalo is None:
        intervalo = get_settings().worker_intervalo_polling_segundos

    asyncio.run(_executar(args.latencia_llm_segundos, intervalo))


if __name__ == "__main__":
    main()
