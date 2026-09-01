from datetime import UTC, datetime
from uuid import uuid4

import pytest

from application.log.registrar_log import RegistrarLogInput, RegistrarLogUseCase
from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from domain.shared.exceptions import EntradaInvalidaError, RecursoNaoEncontradoError
from tests.unit.application.aluno.fakes import AlunoRepositorioFake
from tests.unit.application.log.fakes import LogRepositorioFake
from tests.unit.application.processamento.fakes import ProcessamentoRepositorioFake


def _aluno() -> Aluno:
    return Aluno(
        id=uuid4(),
        nome="Aluno Teste",
        email="aluno@teste.com",
        matricula="2023000001",
        grupo_experimental=GrupoExperimental.EXPERIMENTAL,
        data_cadastro=datetime.now(UTC),
    )


def _processamento(aluno_id: object) -> Processamento:
    return Processamento(
        id=uuid4(),
        aluno_id=aluno_id,  # type: ignore[arg-type]
        material_didatico_id=uuid4(),
        perfil_id=uuid4(),
        status=StatusProcessamento.PENDENTE,
        modelo_ia=None,
        data_criacao=datetime.now(UTC),
        inicio=None,
        fim=None,
        erro=None,
    )


async def test_registra_log_sem_processamento() -> None:
    aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    processamentos = ProcessamentoRepositorioFake()
    logs = LogRepositorioFake()

    resultado = await RegistrarLogUseCase(alunos, processamentos, logs).executar(
        RegistrarLogInput(
            aluno_id=aluno.id,
            processamento_id=None,
            acao="acesso_disciplina",
            descricao=None,
        )
    )

    assert resultado.acao == "acesso_disciplina"
    assert resultado.processamento_id is None


async def test_registra_log_com_processamento_existente() -> None:
    aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    processamento = _processamento(aluno.id)
    processamentos = ProcessamentoRepositorioFake()
    processamentos.semear(processamento)
    logs = LogRepositorioFake()

    resultado = await RegistrarLogUseCase(alunos, processamentos, logs).executar(
        RegistrarLogInput(
            aluno_id=aluno.id,
            processamento_id=processamento.id,
            acao="download_material_personalizado",
            descricao="Download concluído.",
        )
    )

    assert resultado.processamento_id == processamento.id
    assert resultado.descricao == "Download concluído."


async def test_aluno_inexistente_levanta_recurso_nao_encontrado() -> None:
    alunos = AlunoRepositorioFake()
    processamentos = ProcessamentoRepositorioFake()
    logs = LogRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await RegistrarLogUseCase(alunos, processamentos, logs).executar(
            RegistrarLogInput(
                aluno_id=uuid4(), processamento_id=None, acao="acesso_disciplina", descricao=None
            )
        )

    assert excinfo.value.code == "ALUNO_NAO_ENCONTRADO"


async def test_processamento_informado_inexistente_levanta_recurso_nao_encontrado() -> None:
    aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(aluno)
    processamentos = ProcessamentoRepositorioFake()
    logs = LogRepositorioFake()

    with pytest.raises(RecursoNaoEncontradoError) as excinfo:
        await RegistrarLogUseCase(alunos, processamentos, logs).executar(
            RegistrarLogInput(
                aluno_id=aluno.id,
                processamento_id=uuid4(),
                acao="fim_processamento",
                descricao=None,
            )
        )

    assert excinfo.value.code == "PROCESSAMENTO_NAO_ENCONTRADO"


async def test_aluno_id_divergente_do_dono_do_processamento_levanta_entrada_invalida(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # aluno_id e processamento_id não podem apontar para pessoas diferentes — mesma proteção
    # de RegistrarAcessoUseCase (Documento 4, §13.2), aqui contra corrupção da auditoria.
    dono_do_processamento = _aluno()
    outro_aluno = _aluno()
    alunos = AlunoRepositorioFake()
    await alunos.adicionar(dono_do_processamento)
    await alunos.adicionar(outro_aluno)
    processamento = _processamento(dono_do_processamento.id)
    processamentos = ProcessamentoRepositorioFake()
    processamentos.semear(processamento)
    logs = LogRepositorioFake()

    with caplog.at_level("WARNING"), pytest.raises(EntradaInvalidaError) as excinfo:
        await RegistrarLogUseCase(alunos, processamentos, logs).executar(
            RegistrarLogInput(
                aluno_id=outro_aluno.id,
                processamento_id=processamento.id,
                acao="download_material_personalizado",
                descricao=None,
            )
        )

    assert excinfo.value.code == "ALUNO_ID_INVALIDO"
    assert any(r.levelname == "WARNING" for r in caplog.records)
    # Nenhum registro parcial: a rejeição acontece antes de qualquer escrita.
    itens, total = await logs.listar_por_processamento_id(
        processamento.id, pagina=1, tamanho_pagina=20
    )
    assert itens == []
    assert total == 0
