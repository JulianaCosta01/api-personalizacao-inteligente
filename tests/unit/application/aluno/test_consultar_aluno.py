from datetime import UTC, datetime
from uuid import uuid4

import pytest

from application.aluno.consultar_aluno import ConsultarAlunoUseCase
from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.shared.exceptions import RecursoNaoEncontradoError

from .fakes import AlunoRepositorioFake


async def test_retorna_aluno_quando_encontrado() -> None:
    repositorio = AlunoRepositorioFake()
    aluno = Aluno(
        id=uuid4(),
        nome="Kristiano",
        email="kristiano@discente.ufma.br",
        matricula="123",
        grupo_experimental=GrupoExperimental.CONTROLE,
        data_cadastro=datetime.now(UTC),
    )
    await repositorio.adicionar(aluno)

    resultado = await ConsultarAlunoUseCase(repositorio).executar(aluno.id)

    assert resultado == aluno


async def test_levanta_recurso_nao_encontrado_quando_id_nao_existe() -> None:
    repositorio = AlunoRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError):
        await ConsultarAlunoUseCase(repositorio).executar(uuid4())
