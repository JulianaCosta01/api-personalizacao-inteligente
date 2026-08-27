"""Coleta as métricas específicas do MPI (fila, Worker, duplicação) após uma execução do teste
de carga da Fase 10, Task 2, e grava um resultado objetivo em JSON.

As métricas HTTP (throughput, latência média, p50/p95/p99, distribuição de status) já são
geradas nativamente pelo Locust via `--csv=<prefixo>` — este script não as recalcula, só referencia
os arquivos gerados. O que falta depois de uma execução do Locust é o que só o próprio banco sabe:
quantos Processamentos ficaram em cada status, se a fila drenou por completo e se algum
Processamento gerou mais de um MaterialPersonalizado (duplicação de claim/processamento).

Uso, depois de uma execução do Locust com --csv:
    PYTHONPATH=src uv run python -m loadtest.relatorio --csv-prefixo loadtest/resultados/carga
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from infrastructure.database.models.material_personalizado import (
    MaterialPersonalizado as MaterialPersonalizadoModel,
)
from infrastructure.database.models.processamento import Processamento as ProcessamentoModel
from infrastructure.database.session import sessao_transacional
from infrastructure.queue.models import MensagemFila


async def coletar() -> dict[str, object]:
    async with sessao_transacional() as session:
        linhas_status = (
            await session.execute(
                select(ProcessamentoModel.status, func.count())
                .select_from(ProcessamentoModel)
                .group_by(ProcessamentoModel.status)
            )
        ).all()
        contagem_por_status: dict[str, int] = {status: total for status, total in linhas_status}

        mensagens_restantes_na_fila = (
            await session.execute(select(func.count()).select_from(MensagemFila))
        ).scalar_one()

        duplicados = (
            await session.execute(
                select(MaterialPersonalizadoModel.processamento_id, func.count())
                .select_from(MaterialPersonalizadoModel)
                .group_by(MaterialPersonalizadoModel.processamento_id)
                .having(func.count() > 1)
            )
        ).all()

    total_processamentos = sum(contagem_por_status.values())
    return {
        "total_processamentos_criados": total_processamentos,
        "processamentos_por_status": contagem_por_status,
        "mensagens_restantes_na_fila": mensagens_restantes_na_fila,
        "fila_drenada_por_completo": mensagens_restantes_na_fila == 0,
        "material_personalizado_duplicado": [str(pid) for pid, _ in duplicados],
        "ausencia_de_duplicacao_confirmada": len(duplicados) == 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Coleta métricas MPI pós-execução do teste de carga (Fase 10, Task 2)."
    )
    parser.add_argument(
        "--csv-prefixo",
        required=True,
        help="Mesmo prefixo passado a `locust --csv=` na execução que gerou os dados a analisar.",
    )
    args = parser.parse_args()

    dados = asyncio.run(coletar())
    dados["coletado_em"] = datetime.now(UTC).isoformat()
    dados["metricas_http_locust"] = {
        "estatisticas_agregadas": f"{args.csv_prefixo}_stats.csv",
        "serie_temporal": f"{args.csv_prefixo}_stats_history.csv",
        "falhas": f"{args.csv_prefixo}_failures.csv",
        "distribuicao_de_status_http": f"{args.csv_prefixo}_status_codes.json",
    }

    saida = Path(f"{args.csv_prefixo}_mpi.json")
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(dados, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print(json.dumps(dados, indent=2, ensure_ascii=False, default=str))
    print(f"\nSalvo em {saida}")


if __name__ == "__main__":
    main()
