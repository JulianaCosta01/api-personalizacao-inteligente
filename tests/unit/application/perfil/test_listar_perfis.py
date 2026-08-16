from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from tests.unit.application.aluno.fakes import AlunoRepositorioFake

from application.perfil.listar_perfis import ListarPerfisInput, ListarPerfisUseCase
from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.perfil.perfil import Perfil
from domain.shared.exceptions import RecursoNaoEncontradoError

from .fakes import PerfilRepositorioFake


def _aluno() -> Aluno:
    return Aluno(
        id=uuid4(),
        nome="Kristiano Fernandes Plácido",
        email="kristiano@discente.ufma.br",
        matricula="2021045123",
        grupo_experimental=GrupoExperimental.EXPERIMENTAL,
        data_cadastro=datetime.now(UTC),
    )


def _perfil(aluno_id: UUID, data_atualizacao: datetime) -> Perfil:
    return Perfil(
        id=uuid4(),
        aluno_id=aluno_id,
        estilo_processamento=EstiloProcessamento.ATIVO,
        percepcao=Percepcao.SENSORIAL,
        entrada=Entrada.VISUAL,
        compreensao=Compreensao.SEQUENCIAL,
        descricao_llm=None,
        data_atualizacao=data_atualizacao,
    )


async def test_lista_paginada() -> None:
    aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    perfis = PerfilRepositorioFake()
    agora = datetime.now(UTC)
    for i in range(3):
        perfis.semear(_perfil(aluno.id, agora - timedelta(days=i)))

    resultado = await ListarPerfisUseCase(alunos, perfis).executar(
        ListarPerfisInput(aluno_id=aluno.id, pagina=1, tamanho_pagina=2)
    )

    assert resultado.total_itens == 3
    assert len(resultado.itens) == 2


async def test_ordena_por_data_atualizacao_decrescente() -> None:
    aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    perfis = PerfilRepositorioFake()
    agora = datetime.now(UTC)
    antigo = _perfil(aluno.id, agora - timedelta(days=1))
    recente = _perfil(aluno.id, agora)
    perfis.semear(antigo)
    perfis.semear(recente)

    resultado = await ListarPerfisUseCase(alunos, perfis).executar(
        ListarPerfisInput(aluno_id=aluno.id)
    )

    assert [p.id for p in resultado.itens] == [recente.id, antigo.id]


async def test_filtra_por_aluno_id() -> None:
    aluno = _aluno()
    outro_aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    await alunos.adicionar(outro_aluno)
    perfis = PerfilRepositorioFake()
    perfis.semear(_perfil(aluno.id, datetime.now(UTC)))
    perfis.semear(_perfil(outro_aluno.id, datetime.now(UTC)))

    resultado = await ListarPerfisUseCase(alunos, perfis).executar(
        ListarPerfisInput(aluno_id=aluno.id)
    )

    assert resultado.total_itens == 1
    assert resultado.itens[0].aluno_id == aluno.id


async def test_aluno_inexistente_levanta_recurso_nao_encontrado() -> None:
    alunos = AlunoRepositorioFake()
    perfis = PerfilRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError):
        await ListarPerfisUseCase(alunos, perfis).executar(ListarPerfisInput(aluno_id=uuid4()))
