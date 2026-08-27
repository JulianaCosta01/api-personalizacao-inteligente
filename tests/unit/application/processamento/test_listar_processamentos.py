from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from application.processamento.listar_processamentos import (
    ListarProcessamentosDoAlunoUseCase,
    ListarProcessamentosInput,
)
from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from domain.shared.exceptions import RecursoNaoEncontradoError
from tests.unit.application.aluno.fakes import AlunoRepositorioFake

from .fakes import ProcessamentoRepositorioFake


def _aluno() -> Aluno:
    return Aluno(
        id=uuid4(),
        nome="Kristiano Fernandes Plácido",
        email="kristiano@discente.ufma.br",
        matricula="2021045123",
        grupo_experimental=GrupoExperimental.EXPERIMENTAL,
        data_cadastro=datetime.now(UTC),
    )


def _processamento(aluno_id: UUID, data_criacao: datetime) -> Processamento:
    return Processamento(
        id=uuid4(),
        aluno_id=aluno_id,
        material_didatico_id=uuid4(),
        perfil_id=uuid4(),
        status=StatusProcessamento.PENDENTE,
        modelo_ia=None,
        data_criacao=data_criacao,
        inicio=None,
        fim=None,
        erro=None,
    )


async def test_lista_paginada() -> None:
    aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    processamentos = ProcessamentoRepositorioFake()
    agora = datetime.now(UTC)
    for i in range(3):
        processamentos.semear(_processamento(aluno.id, agora - timedelta(minutes=i)))

    resultado = await ListarProcessamentosDoAlunoUseCase(alunos, processamentos).executar(
        ListarProcessamentosInput(aluno_id=aluno.id, pagina=1, tamanho_pagina=2)
    )

    assert resultado.total_itens == 3
    assert len(resultado.itens) == 2


async def test_ordena_por_data_criacao_decrescente() -> None:
    aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    processamentos = ProcessamentoRepositorioFake()
    agora = datetime.now(UTC)
    antigo = _processamento(aluno.id, agora - timedelta(minutes=1))
    recente = _processamento(aluno.id, agora)
    processamentos.semear(antigo)
    processamentos.semear(recente)

    resultado = await ListarProcessamentosDoAlunoUseCase(alunos, processamentos).executar(
        ListarProcessamentosInput(aluno_id=aluno.id)
    )

    assert [p.id for p in resultado.itens] == [recente.id, antigo.id]


async def test_filtra_por_aluno_id() -> None:
    aluno = _aluno()
    outro_aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    await alunos.adicionar(outro_aluno)
    processamentos = ProcessamentoRepositorioFake()
    processamentos.semear(_processamento(aluno.id, datetime.now(UTC)))
    processamentos.semear(_processamento(outro_aluno.id, datetime.now(UTC)))

    resultado = await ListarProcessamentosDoAlunoUseCase(alunos, processamentos).executar(
        ListarProcessamentosInput(aluno_id=aluno.id)
    )

    assert resultado.total_itens == 1
    assert resultado.itens[0].aluno_id == aluno.id


async def test_aluno_inexistente_levanta_recurso_nao_encontrado() -> None:
    alunos = AlunoRepositorioFake()
    processamentos = ProcessamentoRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await ListarProcessamentosDoAlunoUseCase(alunos, processamentos).executar(
            ListarProcessamentosInput(aluno_id=uuid4())
        )

    assert excinfo.value.code == "ALUNO_NAO_ENCONTRADO"
