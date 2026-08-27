from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.log.log_interacao import LogInteracao
from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.perfil.perfil import Perfil
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from infrastructure.database.aluno.aluno_repository import AlunoRepositorySQLAlchemy
from infrastructure.database.log.log_repository import LogRepositorySQLAlchemy
from infrastructure.database.material.material_repository import MaterialRepositorySQLAlchemy
from infrastructure.database.perfil.perfil_repository import PerfilRepositorySQLAlchemy
from infrastructure.database.processamento.processamento_repository import (
    ProcessamentoRepositorySQLAlchemy,
)


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


async def _criar_processamento(session: AsyncSession, aluno_id: UUID) -> Processamento:
    material = MaterialDidatico(
        id=uuid4(),
        titulo="Introdução a Grafos",
        nome_arquivo=f"{uuid4()}.pdf",
        tipo_arquivo=TipoArquivo.PDF,
        caminho_storage=f"materiais/{uuid4()}.pdf",
        versao=1,
        data_upload=datetime.now(UTC),
    )
    await MaterialRepositorySQLAlchemy(session).adicionar(material)

    perfil = Perfil(
        id=uuid4(),
        aluno_id=aluno_id,
        estilo_processamento=EstiloProcessamento.ATIVO,
        percepcao=Percepcao.SENSORIAL,
        entrada=Entrada.VISUAL,
        compreensao=Compreensao.SEQUENCIAL,
        descricao_llm=None,
        data_atualizacao=datetime.now(UTC),
    )
    await PerfilRepositorySQLAlchemy(session).adicionar(perfil)

    processamento = Processamento(
        id=uuid4(),
        aluno_id=aluno_id,
        material_didatico_id=material.id,
        perfil_id=perfil.id,
        status=StatusProcessamento.PENDENTE,
        modelo_ia=None,
        data_criacao=datetime.now(UTC),
        inicio=None,
        fim=None,
        erro=None,
    )
    await ProcessamentoRepositorySQLAlchemy(session).adicionar(processamento)
    return processamento


def _log(
    aluno_id: UUID, processamento_id: UUID | None, timestamp: datetime | None = None
) -> LogInteracao:
    return LogInteracao(
        id=uuid4(),
        aluno_id=aluno_id,
        processamento_id=processamento_id,
        acao="leitura_material_personalizado",
        descricao=None,
        timestamp=timestamp or datetime.now(UTC),
    )


async def test_adiciona_log_sem_processamento(db_session: AsyncSession) -> None:
    aluno = await _criar_aluno(db_session)
    repositorio = LogRepositorySQLAlchemy(db_session)
    log = _log(aluno.id, None)

    await repositorio.adicionar(log)

    itens, total = await repositorio.listar_por_processamento_id(
        uuid4(), pagina=1, tamanho_pagina=20
    )
    assert total == 0
    assert itens == []


async def test_lista_logs_do_processamento_ordenados_por_timestamp_crescente(
    db_session: AsyncSession,
) -> None:
    aluno = await _criar_aluno(db_session)
    processamento = await _criar_processamento(db_session, aluno.id)
    repositorio = LogRepositorySQLAlchemy(db_session)
    agora = datetime.now(UTC)
    recente = _log(aluno.id, processamento.id, agora)
    antigo = _log(aluno.id, processamento.id, agora - timedelta(minutes=1))
    await repositorio.adicionar(recente)
    await repositorio.adicionar(antigo)

    itens, total = await repositorio.listar_por_processamento_id(
        processamento.id, pagina=1, tamanho_pagina=20
    )

    assert total == 2
    assert [log.id for log in itens] == [antigo.id, recente.id]


async def test_lista_filtra_por_processamento_id(db_session: AsyncSession) -> None:
    aluno = await _criar_aluno(db_session)
    processamento1 = await _criar_processamento(db_session, aluno.id)
    processamento2 = await _criar_processamento(db_session, aluno.id)
    repositorio = LogRepositorySQLAlchemy(db_session)
    await repositorio.adicionar(_log(aluno.id, processamento1.id))
    await repositorio.adicionar(_log(aluno.id, processamento2.id))

    itens, total = await repositorio.listar_por_processamento_id(
        processamento1.id, pagina=1, tamanho_pagina=20
    )

    assert total == 1
    assert itens[0].processamento_id == processamento1.id


async def test_lista_retorna_total_e_itens_paginados(db_session: AsyncSession) -> None:
    aluno = await _criar_aluno(db_session)
    processamento = await _criar_processamento(db_session, aluno.id)
    repositorio = LogRepositorySQLAlchemy(db_session)
    for _ in range(3):
        await repositorio.adicionar(_log(aluno.id, processamento.id))

    itens, total = await repositorio.listar_por_processamento_id(
        processamento.id, pagina=1, tamanho_pagina=2
    )

    assert total == 3
    assert len(itens) == 2


async def test_adicionar_com_aluno_inexistente_levanta_erro_de_integridade(
    db_session: AsyncSession,
) -> None:
    repositorio = LogRepositorySQLAlchemy(db_session)

    with pytest.raises(IntegrityError):
        await repositorio.adicionar(_log(uuid4(), None))


async def test_adicionar_com_processamento_inexistente_levanta_erro_de_integridade(
    db_session: AsyncSession,
) -> None:
    aluno = await _criar_aluno(db_session)
    repositorio = LogRepositorySQLAlchemy(db_session)

    with pytest.raises(IntegrityError):
        await repositorio.adicionar(_log(aluno.id, uuid4()))
