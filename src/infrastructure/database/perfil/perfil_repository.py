from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from application.ports.perfil_repository import IPerfilRepository
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.perfil.perfil import Perfil
from infrastructure.database.models.perfil import PerfilAprendizagem as PerfilModel


class PerfilRepositorySQLAlchemy(IPerfilRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def adicionar(self, perfil: Perfil) -> None:
        self._session.add(_para_modelo(perfil))
        await self._session.flush()

    async def atualizar(self, perfil: Perfil) -> None:
        modelo = await self._session.get(PerfilModel, perfil.id)
        if modelo is None:
            raise LookupError(f"Perfil {perfil.id} não encontrado para atualização.")
        modelo.descricao_llm = perfil.descricao_llm
        await self._session.flush()

    async def obter_por_id(self, id: UUID) -> Perfil | None:
        modelo = await self._session.get(PerfilModel, id)
        return _para_dominio(modelo) if modelo is not None else None

    async def obter_mais_recente_por_aluno_id(self, aluno_id: UUID) -> Perfil | None:
        consulta = (
            select(PerfilModel)
            .where(PerfilModel.aluno_id == aluno_id)
            .order_by(PerfilModel.data_atualizacao.desc())
            .limit(1)
        )
        modelo = (await self._session.execute(consulta)).scalar_one_or_none()
        return _para_dominio(modelo) if modelo is not None else None

    async def listar_por_aluno_id(
        self, aluno_id: UUID, pagina: int, tamanho_pagina: int
    ) -> tuple[list[Perfil], int]:
        consulta_total = (
            select(func.count()).select_from(PerfilModel).where(PerfilModel.aluno_id == aluno_id)
        )
        total = (await self._session.execute(consulta_total)).scalar_one()

        consulta = (
            select(PerfilModel)
            .where(PerfilModel.aluno_id == aluno_id)
            .order_by(PerfilModel.data_atualizacao.desc())
            .offset((pagina - 1) * tamanho_pagina)
            .limit(tamanho_pagina)
        )
        modelos = (await self._session.execute(consulta)).scalars().all()
        return [_para_dominio(m) for m in modelos], total


def _para_dominio(modelo: PerfilModel) -> Perfil:
    return Perfil(
        id=modelo.id,
        aluno_id=modelo.aluno_id,
        estilo_processamento=EstiloProcessamento(modelo.estilo_processamento),
        percepcao=Percepcao(modelo.percepcao),
        entrada=Entrada(modelo.entrada),
        compreensao=Compreensao(modelo.compreensao),
        descricao_llm=modelo.descricao_llm,
        data_atualizacao=modelo.data_atualizacao,
    )


def _para_modelo(perfil: Perfil) -> PerfilModel:
    return PerfilModel(
        id=perfil.id,
        aluno_id=perfil.aluno_id,
        estilo_processamento=perfil.estilo_processamento.value,
        percepcao=perfil.percepcao.value,
        entrada=perfil.entrada.value,
        compreensao=perfil.compreensao.value,
        descricao_llm=perfil.descricao_llm,
        data_atualizacao=perfil.data_atualizacao,
    )
