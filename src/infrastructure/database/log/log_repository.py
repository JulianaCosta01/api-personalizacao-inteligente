from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from application.ports.log_repository import ILogRepository
from domain.log.log_interacao import LogInteracao
from infrastructure.database.models.log import LogInteracao as LogInteracaoModel


class LogRepositorySQLAlchemy(ILogRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def adicionar(self, log: LogInteracao) -> None:
        self._session.add(_para_modelo(log))
        await self._session.flush()

    async def listar_por_processamento_id(
        self, processamento_id: UUID, pagina: int, tamanho_pagina: int
    ) -> tuple[list[LogInteracao], int]:
        consulta_total = (
            select(func.count())
            .select_from(LogInteracaoModel)
            .where(LogInteracaoModel.processamento_id == processamento_id)
        )
        total = (await self._session.execute(consulta_total)).scalar_one()

        # Ordenado por timestamp crescente, para reconstruir a
        # linha do tempo de uma solicitação.
        consulta = (
            select(LogInteracaoModel)
            .where(LogInteracaoModel.processamento_id == processamento_id)
            .order_by(LogInteracaoModel.timestamp.asc())
            .offset((pagina - 1) * tamanho_pagina)
            .limit(tamanho_pagina)
        )
        modelos = (await self._session.execute(consulta)).scalars().all()
        return [_para_dominio(m) for m in modelos], total


def _para_dominio(modelo: LogInteracaoModel) -> LogInteracao:
    return LogInteracao(
        id=modelo.id,
        aluno_id=modelo.aluno_id,
        processamento_id=modelo.processamento_id,
        acao=modelo.acao,
        descricao=modelo.descricao,
        timestamp=modelo.timestamp,
    )


def _para_modelo(log: LogInteracao) -> LogInteracaoModel:
    return LogInteracaoModel(
        id=log.id,
        aluno_id=log.aluno_id,
        processamento_id=log.processamento_id,
        acao=log.acao,
        descricao=log.descricao,
        timestamp=log.timestamp,
    )
