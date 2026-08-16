from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.perfil.perfil import Perfil
from infrastructure.database.aluno.aluno_repository import AlunoRepositorySQLAlchemy
from infrastructure.database.perfil.perfil_repository import PerfilRepositorySQLAlchemy


async def _criar_aluno(session: AsyncSession) -> Aluno:
    aluno = Aluno(
        id=uuid4(),
        nome="Kristiano Fernandes Plácido",
        email=f"{uuid4()}@discente.ufma.br",
        matricula=str(uuid4())[:20],
        grupo_experimental=GrupoExperimental.EXPERIMENTAL,
        data_cadastro=datetime.now(UTC),
    )
    await AlunoRepositorySQLAlchemy(session).adicionar(aluno)
    return aluno


def _perfil(aluno_id: UUID, data_atualizacao: datetime | None = None) -> Perfil:
    return Perfil(
        id=uuid4(),
        aluno_id=aluno_id,
        estilo_processamento=EstiloProcessamento.ATIVO,
        percepcao=Percepcao.SENSORIAL,
        entrada=Entrada.VISUAL,
        compreensao=Compreensao.SEQUENCIAL,
        descricao_llm=None,
        data_atualizacao=data_atualizacao or datetime.now(UTC),
    )


async def test_adiciona_e_obtem_mais_recente(db_session: AsyncSession) -> None:
    aluno = await _criar_aluno(db_session)
    repositorio = PerfilRepositorySQLAlchemy(db_session)
    await repositorio.adicionar(_perfil(aluno.id))

    encontrado = await repositorio.obter_mais_recente_por_aluno_id(aluno.id)

    assert encontrado is not None
    assert encontrado.aluno_id == aluno.id


async def test_obter_mais_recente_retorna_none_quando_aluno_sem_perfil(
    db_session: AsyncSession,
) -> None:
    aluno = await _criar_aluno(db_session)
    repositorio = PerfilRepositorySQLAlchemy(db_session)

    assert await repositorio.obter_mais_recente_por_aluno_id(aluno.id) is None


async def test_obter_mais_recente_retorna_o_de_maior_data_atualizacao(
    db_session: AsyncSession,
) -> None:
    aluno = await _criar_aluno(db_session)
    repositorio = PerfilRepositorySQLAlchemy(db_session)
    agora = datetime.now(UTC)
    antigo = _perfil(aluno.id, agora - timedelta(days=1))
    recente = _perfil(aluno.id, agora)
    await repositorio.adicionar(antigo)
    await repositorio.adicionar(recente)

    encontrado = await repositorio.obter_mais_recente_por_aluno_id(aluno.id)

    assert encontrado is not None
    assert encontrado.id == recente.id


async def test_atualizar_persiste_descricao_llm(db_session: AsyncSession) -> None:
    aluno = await _criar_aluno(db_session)
    repositorio = PerfilRepositorySQLAlchemy(db_session)
    perfil = _perfil(aluno.id)
    await repositorio.adicionar(perfil)

    perfil.descricao_llm = "Descrição gerada pelo Gemini."
    await repositorio.atualizar(perfil)

    encontrado = await repositorio.obter_mais_recente_por_aluno_id(aluno.id)
    assert encontrado is not None
    assert encontrado.descricao_llm == "Descrição gerada pelo Gemini."


async def test_atualizar_perfil_inexistente_levanta_lookup_error(
    db_session: AsyncSession,
) -> None:
    aluno = await _criar_aluno(db_session)
    repositorio = PerfilRepositorySQLAlchemy(db_session)

    with pytest.raises(LookupError):
        await repositorio.atualizar(_perfil(aluno.id))


async def test_listar_retorna_total_e_itens_paginados(db_session: AsyncSession) -> None:
    aluno = await _criar_aluno(db_session)
    repositorio = PerfilRepositorySQLAlchemy(db_session)
    for _ in range(3):
        await repositorio.adicionar(_perfil(aluno.id))

    itens, total = await repositorio.listar_por_aluno_id(aluno.id, pagina=1, tamanho_pagina=2)

    assert total == 3
    assert len(itens) == 2


async def test_listar_filtra_por_aluno_id(db_session: AsyncSession) -> None:
    aluno1 = await _criar_aluno(db_session)
    aluno2 = await _criar_aluno(db_session)
    repositorio = PerfilRepositorySQLAlchemy(db_session)
    await repositorio.adicionar(_perfil(aluno1.id))
    await repositorio.adicionar(_perfil(aluno2.id))

    itens, total = await repositorio.listar_por_aluno_id(aluno1.id, pagina=1, tamanho_pagina=20)

    assert total == 1
    assert itens[0].aluno_id == aluno1.id


async def test_listar_ordena_por_data_atualizacao_decrescente(db_session: AsyncSession) -> None:
    aluno = await _criar_aluno(db_session)
    repositorio = PerfilRepositorySQLAlchemy(db_session)
    agora = datetime.now(UTC)
    antigo = _perfil(aluno.id, agora - timedelta(days=1))
    recente = _perfil(aluno.id, agora)
    await repositorio.adicionar(antigo)
    await repositorio.adicionar(recente)

    itens, _total = await repositorio.listar_por_aluno_id(aluno.id, pagina=1, tamanho_pagina=20)

    assert [p.id for p in itens] == [recente.id, antigo.id]
