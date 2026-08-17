from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.perfil.perfil import Perfil
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from infrastructure.database.aluno.aluno_repository import AlunoRepositorySQLAlchemy
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


async def _criar_material(session: AsyncSession) -> MaterialDidatico:
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
    return material


async def _criar_perfil(session: AsyncSession, aluno_id: UUID) -> Perfil:
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
    return perfil


async def _cadeia_completa(session: AsyncSession) -> tuple[Aluno, MaterialDidatico, Perfil]:
    aluno = await _criar_aluno(session)
    material = await _criar_material(session)
    perfil = await _criar_perfil(session, aluno.id)
    return aluno, material, perfil


def _processamento(
    aluno_id: UUID, material_id: UUID, perfil_id: UUID, data_criacao: datetime | None = None
) -> Processamento:
    return Processamento(
        id=uuid4(),
        aluno_id=aluno_id,
        material_didatico_id=material_id,
        perfil_id=perfil_id,
        status=StatusProcessamento.PENDENTE,
        modelo_ia=None,
        data_criacao=data_criacao or datetime.now(UTC),
        inicio=None,
        fim=None,
        erro=None,
    )


async def test_adiciona_e_obtem_por_id(db_session: AsyncSession) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    processamento = _processamento(aluno.id, material.id, perfil.id)

    await repositorio.adicionar(processamento)
    encontrado = await repositorio.obter_por_id(processamento.id)

    assert encontrado is not None
    assert encontrado.aluno_id == aluno.id
    assert encontrado.material_didatico_id == material.id
    assert encontrado.perfil_id == perfil.id
    assert encontrado.status == StatusProcessamento.PENDENTE


async def test_obter_por_id_inexistente_retorna_none(db_session: AsyncSession) -> None:
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)

    assert await repositorio.obter_por_id(uuid4()) is None


async def test_atualizar_persiste_status_modelo_ia_inicio_fim_erro(
    db_session: AsyncSession,
) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    processamento = _processamento(aluno.id, material.id, perfil.id)
    await repositorio.adicionar(processamento)

    agora = datetime.now(UTC)
    processamento.status = StatusProcessamento.ERRO
    processamento.modelo_ia = "gemini-3.1-flash-lite"
    processamento.inicio = agora
    processamento.fim = agora
    processamento.erro = "Falha ao publicar a solicitação na fila de processamento."
    await repositorio.atualizar(processamento)

    encontrado = await repositorio.obter_por_id(processamento.id)
    assert encontrado is not None
    assert encontrado.status == StatusProcessamento.ERRO
    assert encontrado.modelo_ia == "gemini-3.1-flash-lite"
    assert encontrado.erro == "Falha ao publicar a solicitação na fila de processamento."


async def test_atualizar_processamento_inexistente_levanta_lookup_error(
    db_session: AsyncSession,
) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)

    with pytest.raises(LookupError):
        await repositorio.atualizar(_processamento(aluno.id, material.id, perfil.id))


async def test_listar_retorna_total_e_itens_paginados(db_session: AsyncSession) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    for _ in range(3):
        await repositorio.adicionar(_processamento(aluno.id, material.id, perfil.id))

    itens, total = await repositorio.listar_por_aluno_id(aluno.id, pagina=1, tamanho_pagina=2)

    assert total == 3
    assert len(itens) == 2


async def test_listar_filtra_por_aluno_id(db_session: AsyncSession) -> None:
    aluno1, material, perfil1 = await _cadeia_completa(db_session)
    aluno2 = await _criar_aluno(db_session)
    perfil2 = await _criar_perfil(db_session, aluno2.id)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    await repositorio.adicionar(_processamento(aluno1.id, material.id, perfil1.id))
    await repositorio.adicionar(_processamento(aluno2.id, material.id, perfil2.id))

    itens, total = await repositorio.listar_por_aluno_id(aluno1.id, pagina=1, tamanho_pagina=20)

    assert total == 1
    assert itens[0].aluno_id == aluno1.id


async def test_listar_ordena_por_data_criacao_decrescente(db_session: AsyncSession) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    agora = datetime.now(UTC)
    antigo = _processamento(aluno.id, material.id, perfil.id, agora - timedelta(minutes=1))
    recente = _processamento(aluno.id, material.id, perfil.id, agora)
    await repositorio.adicionar(antigo)
    await repositorio.adicionar(recente)

    itens, _total = await repositorio.listar_por_aluno_id(aluno.id, pagina=1, tamanho_pagina=20)

    assert [p.id for p in itens] == [recente.id, antigo.id]


async def test_adicionar_com_aluno_inexistente_levanta_erro_de_integridade(
    db_session: AsyncSession,
) -> None:
    _, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)

    with pytest.raises(IntegrityError):
        await repositorio.adicionar(_processamento(uuid4(), material.id, perfil.id))


async def test_adicionar_com_material_inexistente_levanta_erro_de_integridade(
    db_session: AsyncSession,
) -> None:
    aluno, _, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)

    with pytest.raises(IntegrityError):
        await repositorio.adicionar(_processamento(aluno.id, uuid4(), perfil.id))


async def test_adicionar_com_perfil_inexistente_levanta_erro_de_integridade(
    db_session: AsyncSession,
) -> None:
    aluno, material, _ = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)

    with pytest.raises(IntegrityError):
        await repositorio.adicionar(_processamento(aluno.id, material.id, uuid4()))


def _processamento_em_processamento(
    aluno_id: UUID, material_id: UUID, perfil_id: UUID, inicio: datetime
) -> Processamento:
    processamento = _processamento(aluno_id, material_id, perfil_id)
    processamento.status = StatusProcessamento.EM_PROCESSAMENTO
    processamento.inicio = inicio
    return processamento


async def test_liberar_presos_devolve_para_pendente_processamento_antigo(
    db_session: AsyncSession,
) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    preso = _processamento_em_processamento(
        aluno.id, material.id, perfil.id, datetime.now(UTC) - timedelta(minutes=20)
    )
    await repositorio.adicionar(preso)

    liberados = await repositorio.liberar_presos(timedelta(minutes=10))

    assert liberados == [preso.id]
    atualizado = await repositorio.obter_por_id(preso.id)
    assert atualizado is not None
    assert atualizado.status == StatusProcessamento.PENDENTE


async def test_liberar_presos_nao_afeta_processamento_em_processamento_recente(
    db_session: AsyncSession,
) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    recente = _processamento_em_processamento(aluno.id, material.id, perfil.id, datetime.now(UTC))
    await repositorio.adicionar(recente)

    liberados = await repositorio.liberar_presos(timedelta(minutes=10))

    assert liberados == []
    atualizado = await repositorio.obter_por_id(recente.id)
    assert atualizado is not None
    assert atualizado.status == StatusProcessamento.EM_PROCESSAMENTO


async def test_liberar_presos_nao_afeta_processamento_pendente_ou_concluido(
    db_session: AsyncSession,
) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    pendente = _processamento(aluno.id, material.id, perfil.id)
    concluido = _processamento_em_processamento(
        aluno.id, material.id, perfil.id, datetime.now(UTC) - timedelta(minutes=20)
    )
    concluido.status = StatusProcessamento.CONCLUIDO
    await repositorio.adicionar(pendente)
    await repositorio.adicionar(concluido)

    liberados = await repositorio.liberar_presos(timedelta(seconds=0))

    assert liberados == []
