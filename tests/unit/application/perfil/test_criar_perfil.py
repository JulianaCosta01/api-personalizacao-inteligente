from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from application.perfil.criar_perfil import CriarPerfilInput, CriarPerfilUseCase
from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.shared.exceptions import RecursoNaoEncontradoError
from tests.unit.application.aluno.fakes import AlunoRepositorioFake

from .fakes import LLMFake, PerfilRepositorioFake


def _aluno(id: UUID | None = None) -> Aluno:
    return Aluno(
        id=id or uuid4(),
        nome="Kristiano Fernandes Plácido",
        email="kristiano@discente.ufma.br",
        matricula="2021045123",
        grupo_experimental=GrupoExperimental.EXPERIMENTAL,
        data_cadastro=datetime.now(UTC),
    )


def _input(aluno_id: UUID) -> CriarPerfilInput:
    return CriarPerfilInput(
        aluno_id=aluno_id,
        estilo_processamento=EstiloProcessamento.ATIVO,
        percepcao=Percepcao.SENSORIAL,
        entrada=Entrada.VISUAL,
        compreensao=Compreensao.SEQUENCIAL,
    )


async def test_cria_perfil_com_aluno_existente() -> None:
    aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    perfis = PerfilRepositorioFake()

    perfil = await CriarPerfilUseCase(alunos, perfis, LLMFake()).executar(_input(aluno.id))

    assert perfil.aluno_id == aluno.id
    assert await perfis.obter_mais_recente_por_aluno_id(aluno.id) is not None


async def test_aluno_inexistente_levanta_recurso_nao_encontrado() -> None:
    alunos = AlunoRepositorioFake()
    perfis = PerfilRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError):
        await CriarPerfilUseCase(alunos, perfis, LLMFake()).executar(_input(uuid4()))


async def test_criacao_com_llm_funcionando_preenche_descricao() -> None:
    aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    perfis = PerfilRepositorioFake()
    llm = LLMFake(descricao="Perfil com forte tendência à experimentação prática.")

    perfil = await CriarPerfilUseCase(alunos, perfis, llm).executar(_input(aluno.id))

    assert perfil.descricao_llm == "Perfil com forte tendência à experimentação prática."
    assert llm.chamadas == 1


async def test_llm_retornando_none_persiste_perfil_sem_descricao() -> None:
    aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    perfis = PerfilRepositorioFake()
    llm = LLMFake(descricao=None)

    perfil = await CriarPerfilUseCase(alunos, perfis, llm).executar(_input(aluno.id))

    assert perfil.descricao_llm is None


async def test_excecao_do_llm_nao_impede_criacao_do_perfil() -> None:
    aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    perfis = PerfilRepositorioFake()
    llm = LLMFake(levantar=True)

    perfil = await CriarPerfilUseCase(alunos, perfis, llm).executar(_input(aluno.id))

    assert perfil.descricao_llm is None
    assert await perfis.obter_mais_recente_por_aluno_id(aluno.id) is not None
