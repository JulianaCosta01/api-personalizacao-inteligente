from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from application.ports.aluno_repository import IAlunoRepository
from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.shared.exceptions import ConflitoDeEstadoError
from infrastructure.database.models.aluno import Aluno as AlunoModel


class AlunoRepositorySQLAlchemy(IAlunoRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def obter_por_id(self, id: UUID) -> Aluno | None:
        modelo = await self._session.get(AlunoModel, id)
        return _para_dominio(modelo) if modelo is not None else None

    async def obter_por_matricula(self, matricula: str) -> Aluno | None:
        resultado = await self._session.execute(
            select(AlunoModel).where(AlunoModel.matricula == matricula)
        )
        modelo = resultado.scalar_one_or_none()
        return _para_dominio(modelo) if modelo is not None else None

    async def adicionar(self, aluno: Aluno) -> None:
        self._session.add(_para_modelo(aluno))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # Cobre a corrida entre obter_por_matricula do caso de uso e este INSERT
            # (uq_aluno_matricula); sem rollback a sessão fica presa em transação abortada.
            await self._session.rollback()
            raise ConflitoDeEstadoError(
                code="ALUNO_MATRICULA_DUPLICADA",
                message="Já existe um aluno cadastrado com esta matrícula.",
                details={"matricula": aluno.matricula},
            ) from exc

    async def atualizar(self, aluno: Aluno) -> None:
        modelo = await self._session.get(AlunoModel, aluno.id)
        if modelo is None:
            raise LookupError(f"Aluno {aluno.id} não encontrado para atualização.")
        modelo.nome = aluno.nome
        modelo.email = aluno.email
        await self._session.flush()


def _para_dominio(modelo: AlunoModel) -> Aluno:
    return Aluno(
        id=modelo.id,
        nome=modelo.nome,
        email=modelo.email,
        matricula=modelo.matricula,
        grupo_experimental=GrupoExperimental(modelo.grupo_experimental),
        data_cadastro=modelo.data_cadastro,
    )


def _para_modelo(aluno: Aluno) -> AlunoModel:
    return AlunoModel(
        id=aluno.id,
        nome=aluno.nome,
        email=aluno.email,
        matricula=aluno.matricula,
        # asyncpg exige str puro para a coluna VARCHAR: StrEnum é um subtipo de
        # str, mas o driver checa o tipo exato, não isinstance.
        grupo_experimental=aluno.grupo_experimental.value,
        data_cadastro=aluno.data_cadastro,
    )
