from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from application.ports.processamento_repository import IProcessamentoRepository
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from infrastructure.database.models.processamento import Processamento as ProcessamentoModel


class ProcessamentoRepositorySQLAlchemy(IProcessamentoRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def adicionar(self, processamento: Processamento) -> None:
        self._session.add(_para_modelo(processamento))
        await self._session.flush()

    async def atualizar(self, processamento: Processamento) -> None:
        modelo = await self._session.get(ProcessamentoModel, processamento.id)
        if modelo is None:
            raise LookupError(f"Processamento {processamento.id} não encontrado para atualização.")
        modelo.status = processamento.status.value
        modelo.modelo_ia = processamento.modelo_ia
        modelo.inicio = processamento.inicio
        modelo.fim = processamento.fim
        modelo.erro = processamento.erro
        await self._session.flush()

    async def obter_por_id(self, id: UUID) -> Processamento | None:
        modelo = await self._session.get(ProcessamentoModel, id)
        return _para_dominio(modelo) if modelo is not None else None

    async def listar_por_aluno_id(
        self, aluno_id: UUID, pagina: int, tamanho_pagina: int
    ) -> tuple[list[Processamento], int]:
        consulta_total = (
            select(func.count())
            .select_from(ProcessamentoModel)
            .where(ProcessamentoModel.aluno_id == aluno_id)
        )
        total = (await self._session.execute(consulta_total)).scalar_one()

        consulta = (
            select(ProcessamentoModel)
            .where(ProcessamentoModel.aluno_id == aluno_id)
            .order_by(ProcessamentoModel.data_criacao.desc())
            .offset((pagina - 1) * tamanho_pagina)
            .limit(tamanho_pagina)
        )
        modelos = (await self._session.execute(consulta)).scalars().all()
        return [_para_dominio(m) for m in modelos], total

    async def liberar_presos(self, idade_maxima: timedelta) -> list[UUID]:
        limite = datetime.now(UTC) - idade_maxima
        instrucao = (
            update(ProcessamentoModel)
            .where(ProcessamentoModel.status == StatusProcessamento.EM_PROCESSAMENTO.value)
            .where(ProcessamentoModel.inicio < limite)
            .values(status=StatusProcessamento.PENDENTE.value)
            .returning(ProcessamentoModel.id)
        )
        resultado = await self._session.execute(instrucao)
        liberados = list(resultado.scalars().all())
        await self._session.flush()
        return liberados


def _para_dominio(modelo: ProcessamentoModel) -> Processamento:
    return Processamento(
        id=modelo.id,
        aluno_id=modelo.aluno_id,
        material_didatico_id=modelo.material_didatico_id,
        perfil_id=modelo.perfil_id,
        status=StatusProcessamento(modelo.status),
        modelo_ia=modelo.modelo_ia,
        data_criacao=modelo.data_criacao,
        inicio=modelo.inicio,
        fim=modelo.fim,
        erro=modelo.erro,
    )


def _para_modelo(processamento: Processamento) -> ProcessamentoModel:
    return ProcessamentoModel(
        id=processamento.id,
        aluno_id=processamento.aluno_id,
        material_didatico_id=processamento.material_didatico_id,
        perfil_id=processamento.perfil_id,
        status=processamento.status.value,
        modelo_ia=processamento.modelo_ia,
        data_criacao=processamento.data_criacao,
        inicio=processamento.inicio,
        fim=processamento.fim,
        erro=processamento.erro,
    )
