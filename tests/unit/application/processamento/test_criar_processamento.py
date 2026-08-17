from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from tests.unit.application.aluno.fakes import AlunoRepositorioFake
from tests.unit.application.material.fakes import MaterialRepositorioFake
from tests.unit.application.perfil.fakes import PerfilRepositorioFake

from application.processamento.criar_processamento import (
    CriarProcessamentoInput,
    CriarProcessamentoUseCase,
)
from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.perfil.perfil import Perfil
from domain.processamento.status_processamento import StatusProcessamento
from domain.shared.exceptions import RecursoNaoEncontradoError, RegraDeNegocioVioladaError

from .fakes import ProcessamentoRepositorioFake, QueueFake


def _aluno() -> Aluno:
    return Aluno(
        id=uuid4(),
        nome="Kristiano Fernandes Plácido",
        email="kristiano@discente.ufma.br",
        matricula="2021045123",
        grupo_experimental=GrupoExperimental.EXPERIMENTAL,
        data_cadastro=datetime.now(UTC),
    )


def _material() -> MaterialDidatico:
    return MaterialDidatico(
        id=uuid4(),
        titulo="Introdução a Grafos",
        nome_arquivo="a1b2c3.pdf",
        tipo_arquivo=TipoArquivo.PDF,
        caminho_storage="materiais/a1b2c3.pdf",
        versao=1,
        data_upload=datetime.now(UTC),
    )


def _perfil(aluno_id: UUID) -> Perfil:
    return Perfil(
        id=uuid4(),
        aluno_id=aluno_id,
        estilo_processamento=EstiloProcessamento.ATIVO,
        percepcao=Percepcao.SENSORIAL,
        entrada=Entrada.VISUAL,
        compreensao=Compreensao.SEQUENCIAL,
        descricao_llm=None,
        data_atualizacao=datetime.now(UTC),
    )


async def _cenario_valido() -> tuple[
    AlunoRepositorioFake,
    PerfilRepositorioFake,
    MaterialRepositorioFake,
    Aluno,
    Perfil,
    MaterialDidatico,
]:
    aluno = _aluno()
    material = _material()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    perfis = PerfilRepositorioFake()
    perfil = _perfil(aluno.id)
    perfis.semear(perfil)
    materiais = MaterialRepositorioFake()
    materiais.semear(material)
    return alunos, perfis, materiais, aluno, perfil, material


async def test_cria_processamento_pendente_e_publica_na_fila() -> None:
    alunos, perfis, materiais, aluno, perfil, material = await _cenario_valido()
    processamentos = ProcessamentoRepositorioFake()
    fila = QueueFake()

    processamento = await CriarProcessamentoUseCase(
        alunos, perfis, materiais, processamentos, fila
    ).executar(CriarProcessamentoInput(aluno_id=aluno.id, material_didatico_id=material.id))

    assert processamento.status == StatusProcessamento.PENDENTE
    assert processamento.perfil_id == perfil.id
    assert processamento.aluno_id == aluno.id
    assert processamento.material_didatico_id == material.id
    assert fila.publicados == [processamento.id]


async def test_aluno_inexistente_levanta_recurso_nao_encontrado() -> None:
    _, perfis, materiais, _, _, material = await _cenario_valido()
    processamentos = ProcessamentoRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await CriarProcessamentoUseCase(
            AlunoRepositorioFake(), perfis, materiais, processamentos, QueueFake()
        ).executar(CriarProcessamentoInput(aluno_id=uuid4(), material_didatico_id=material.id))

    assert excinfo.value.code == "ALUNO_NAO_ENCONTRADO"


async def test_aluno_sem_perfil_levanta_regra_de_negocio_violada() -> None:
    aluno = _aluno()
    material = _material()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    materiais = MaterialRepositorioFake()
    materiais.semear(material)
    processamentos = ProcessamentoRepositorioFake()

    with pytest.raises(RegraDeNegocioVioladaError) as excinfo:
        await CriarProcessamentoUseCase(
            alunos, PerfilRepositorioFake(), materiais, processamentos, QueueFake()
        ).executar(CriarProcessamentoInput(aluno_id=aluno.id, material_didatico_id=material.id))

    assert excinfo.value.code == "PERFIL_NAO_CADASTRADO"


async def test_material_inexistente_levanta_recurso_nao_encontrado() -> None:
    alunos, perfis, materiais, aluno, _, _ = await _cenario_valido()
    processamentos = ProcessamentoRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await CriarProcessamentoUseCase(
            alunos, perfis, materiais, processamentos, QueueFake()
        ).executar(CriarProcessamentoInput(aluno_id=aluno.id, material_didatico_id=uuid4()))

    assert excinfo.value.code == "MATERIAL_NAO_ENCONTRADO"


async def test_falha_na_publicacao_marca_processamento_como_erro_sem_propagar() -> None:
    alunos, perfis, materiais, aluno, _, material = await _cenario_valido()
    processamentos = ProcessamentoRepositorioFake()
    fila = QueueFake(levantar=True)

    processamento = await CriarProcessamentoUseCase(
        alunos, perfis, materiais, processamentos, fila
    ).executar(CriarProcessamentoInput(aluno_id=aluno.id, material_didatico_id=material.id))

    assert processamento.status == StatusProcessamento.ERRO
    assert processamento.erro is not None
    assert processamento.fim is not None


async def test_falha_na_publicacao_persiste_o_status_de_erro() -> None:
    alunos, perfis, materiais, aluno, _, material = await _cenario_valido()
    processamentos = ProcessamentoRepositorioFake()
    fila = QueueFake(levantar=True)

    processamento = await CriarProcessamentoUseCase(
        alunos, perfis, materiais, processamentos, fila
    ).executar(CriarProcessamentoInput(aluno_id=aluno.id, material_didatico_id=material.id))

    persistido = await processamentos.obter_por_id(processamento.id)
    assert persistido is not None
    assert persistido.status == StatusProcessamento.ERRO


async def test_ordem_de_validacao_aluno_antes_de_perfil() -> None:
    _, perfis, materiais, _, _, material = await _cenario_valido()
    processamentos = ProcessamentoRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await CriarProcessamentoUseCase(
            AlunoRepositorioFake(), PerfilRepositorioFake(), materiais, processamentos, QueueFake()
        ).executar(CriarProcessamentoInput(aluno_id=uuid4(), material_didatico_id=material.id))

    assert excinfo.value.code == "ALUNO_NAO_ENCONTRADO"


async def test_ordem_de_validacao_perfil_antes_de_material() -> None:
    aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    processamentos = ProcessamentoRepositorioFake()

    with pytest.raises(RegraDeNegocioVioladaError):
        await CriarProcessamentoUseCase(
            alunos, PerfilRepositorioFake(), MaterialRepositorioFake(), processamentos, QueueFake()
        ).executar(CriarProcessamentoInput(aluno_id=aluno.id, material_didatico_id=uuid4()))
