"""Verifica o SQL real (dialeto PostgreSQL) da devolução à fila e do claim, sem banco.

Os testes de integração exercitam o comportamento no PostgreSQL; estes garantem, sem depender
dele, que as condições de segurança estão de fato no comando enviado (posse, limite de
tentativas, espera e SKIP LOCKED).
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from infrastructure.database.processamento.processamento_repository import (
    ProcessamentoRepositorySQLAlchemy,
)
from infrastructure.queue.fila_postgres import FilaPostgres


class _SessaoCapturadora:
    def __init__(self) -> None:
        self.instrucoes: list[Any] = []

    async def execute(self, instrucao: Any) -> Any:
        self.instrucoes.append(instrucao)
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    async def flush(self) -> None:
        return None


def _sql(instrucao: Any) -> str:
    compilada = instrucao.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    return " ".join(str(compilada).split())


def _em_processamento(tentativas: int = 1) -> Processamento:
    return Processamento(
        id=uuid4(),
        aluno_id=uuid4(),
        material_didatico_id=uuid4(),
        perfil_id=uuid4(),
        status=StatusProcessamento.EM_PROCESSAMENTO,
        modelo_ia=None,
        data_criacao=datetime.now(UTC),
        inicio=datetime(2026, 10, 14, 14, 53, 24, tzinfo=UTC),
        fim=None,
        erro=None,
        tentativas=tentativas,
    )


async def test_devolucao_exige_posse_estado_inicio_e_limite_de_tentativas() -> None:
    sessao = _SessaoCapturadora()
    repositorio = ProcessamentoRepositorySQLAlchemy(cast(AsyncSession, sessao))
    processamento = _em_processamento()

    devolvido = await repositorio.devolver_para_fila_se_dono(
        processamento, datetime(2026, 10, 14, 15, 0, tzinfo=UTC) + timedelta(seconds=30), 3
    )

    assert devolvido is False  # a sessão capturadora não devolve linha
    sql = _sql(sessao.instrucoes[0])
    assert sql.startswith("UPDATE processamento SET")
    assert "status='pendente'" in sql
    assert "disponivel_em='2026-10-14 15:00:30+00:00'" in sql
    assert "WHERE processamento.id = '" in sql
    assert "processamento.status = 'em_processamento'" in sql
    assert "processamento.inicio = '2026-10-14 14:53:24+00:00'" in sql
    assert "processamento.tentativas < 3" in sql
    assert "RETURNING processamento.id" in sql
    # Não toca em fim/erro/tentativas: a devolução não encerra nem conta nada.
    assert "fim=" not in sql and "erro=" not in sql and "tentativas=" not in sql


async def test_claim_ignora_espera_futura_mantem_skip_locked_e_zera_a_espera() -> None:
    sessao = _SessaoCapturadora()

    assert await FilaPostgres(cast(AsyncSession, sessao)).reivindicar_proximo() is None

    sql = _sql(sessao.instrucoes[0])
    assert "processamento.status = 'pendente'" in sql
    assert "processamento.disponivel_em IS NULL OR processamento.disponivel_em <= now()" in sql
    assert "FOR UPDATE OF processamento SKIP LOCKED" in sql
    assert "ORDER BY fila_processamento.criado_em ASC" in sql
    assert "tentativas=(processamento.tentativas + 1)" in sql
    assert "disponivel_em=NULL" in sql  # a nova reivindicação limpa a espera anterior
    assert "inicio=now()" in sql
