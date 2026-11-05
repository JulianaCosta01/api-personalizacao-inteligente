from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.shared.exceptions import ConflitoDeEstadoError
from infrastructure.database.aluno.aluno_repository import AlunoRepositorySQLAlchemy


def _aluno(*, matricula: str | None = None) -> Aluno:
    return Aluno(
        id=uuid4(),
        nome="Kristiano",
        email="kristiano@discente.ufma.br",
        # matricula é String(20): um uuid4() puro (36 chars) estoura a coluna.
        matricula=matricula or str(uuid4())[:20],
        grupo_experimental=GrupoExperimental.EXPERIMENTAL,
        data_cadastro=datetime.now(UTC),
    )


async def test_adiciona_e_busca_por_id(db_session: AsyncSession) -> None:
    repositorio = AlunoRepositorySQLAlchemy(db_session)
    aluno = _aluno()

    await repositorio.adicionar(aluno)

    assert await repositorio.obter_por_id(aluno.id) == aluno


async def test_busca_por_matricula(db_session: AsyncSession) -> None:
    repositorio = AlunoRepositorySQLAlchemy(db_session)
    aluno = _aluno()
    await repositorio.adicionar(aluno)

    assert await repositorio.obter_por_matricula(aluno.matricula) == aluno


async def test_obter_por_id_retorna_none_quando_nao_existe(db_session: AsyncSession) -> None:
    repositorio = AlunoRepositorySQLAlchemy(db_session)

    assert await repositorio.obter_por_id(uuid4()) is None


async def test_obter_por_matricula_retorna_none_quando_nao_existe(
    db_session: AsyncSession,
) -> None:
    repositorio = AlunoRepositorySQLAlchemy(db_session)

    assert await repositorio.obter_por_matricula(str(uuid4())) is None


async def test_matricula_duplicada_levanta_conflito(db_session: AsyncSession) -> None:
    repositorio = AlunoRepositorySQLAlchemy(db_session)
    matricula = str(uuid4())[:20]
    await repositorio.adicionar(_aluno(matricula=matricula))

    with pytest.raises(ConflitoDeEstadoError):
        await repositorio.adicionar(_aluno(matricula=matricula))


async def test_atualizar_persiste_nome_e_email(db_session: AsyncSession) -> None:
    repositorio = AlunoRepositorySQLAlchemy(db_session)
    aluno = _aluno()
    await repositorio.adicionar(aluno)

    aluno.atualizar_cadastro(nome="Novo Nome", email="novo@discente.ufma.br")
    await repositorio.atualizar(aluno)

    encontrado = await repositorio.obter_por_id(aluno.id)
    assert encontrado is not None
    assert encontrado.nome == "Novo Nome"
    assert encontrado.email == "novo@discente.ufma.br"
