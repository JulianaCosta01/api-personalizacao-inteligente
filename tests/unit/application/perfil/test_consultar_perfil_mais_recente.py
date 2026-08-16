from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from tests.unit.application.aluno.fakes import AlunoRepositorioFake

from application.perfil.consultar_perfil_mais_recente import ConsultarPerfilMaisRecenteUseCase
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


async def test_retorna_o_perfil_mais_recente() -> None:
    aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    perfis = PerfilRepositorioFake()
    agora = datetime.now(UTC)
    antigo = _perfil(aluno.id, agora - timedelta(days=1))
    recente = _perfil(aluno.id, agora)
    perfis.semear(antigo)
    perfis.semear(recente)

    resultado = await ConsultarPerfilMaisRecenteUseCase(alunos, perfis).executar(aluno.id)

    assert resultado.id == recente.id


async def test_aluno_existente_sem_perfil_levanta_recurso_nao_encontrado() -> None:
    aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    perfis = PerfilRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await ConsultarPerfilMaisRecenteUseCase(alunos, perfis).executar(aluno.id)

    assert excinfo.value.code == "PERFIL_NAO_ENCONTRADO"


async def test_aluno_inexistente_levanta_recurso_nao_encontrado() -> None:
    alunos = AlunoRepositorioFake()
    perfis = PerfilRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await ConsultarPerfilMaisRecenteUseCase(alunos, perfis).executar(uuid4())

    assert excinfo.value.code == "ALUNO_NAO_ENCONTRADO"
