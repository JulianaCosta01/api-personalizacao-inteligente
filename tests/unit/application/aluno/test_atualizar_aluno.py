from datetime import UTC, datetime
from uuid import uuid4

import pytest

from application.aluno.atualizar_aluno import AtualizarAlunoInput, AtualizarAlunoUseCase
from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.shared.exceptions import RecursoNaoEncontradoError

from .fakes import AlunoRepositorioFake


async def _aluno_existente(repositorio: AlunoRepositorioFake) -> Aluno:
    aluno = Aluno(
        id=uuid4(),
        nome="Kristiano",
        email="kristiano@discente.ufma.br",
        matricula="123",
        grupo_experimental=GrupoExperimental.CONTROLE,
        data_cadastro=datetime.now(UTC),
    )
    await repositorio.adicionar(aluno)
    return aluno


async def test_atualiza_nome_e_email() -> None:
    repositorio = AlunoRepositorioFake()
    aluno = await _aluno_existente(repositorio)

    resultado = await AtualizarAlunoUseCase(repositorio).executar(
        AtualizarAlunoInput(id=aluno.id, nome="Novo Nome", email="novo@discente.ufma.br")
    )

    assert resultado.nome == "Novo Nome"
    assert resultado.email == "novo@discente.ufma.br"
    persistido = await repositorio.obter_por_id(aluno.id)
    assert persistido is not None
    assert persistido.nome == "Novo Nome"


async def test_preserva_matricula_e_grupo_experimental() -> None:
    repositorio = AlunoRepositorioFake()
    aluno = await _aluno_existente(repositorio)

    resultado = await AtualizarAlunoUseCase(repositorio).executar(
        AtualizarAlunoInput(id=aluno.id, nome="Novo Nome", email="novo@discente.ufma.br")
    )

    assert resultado.matricula == "123"
    assert resultado.grupo_experimental == GrupoExperimental.CONTROLE


async def test_levanta_recurso_nao_encontrado_quando_id_nao_existe() -> None:
    repositorio = AlunoRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError):
        await AtualizarAlunoUseCase(repositorio).executar(
            AtualizarAlunoInput(id=uuid4(), nome="X", email="x@x.com")
        )
