import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
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
from infrastructure.database.session import sessao_transacional
from infrastructure.queue.fila_postgres import FilaPostgres
from infrastructure.queue.models import MensagemFila


async def _criar_processamento(session: AsyncSession) -> Processamento:
    aluno = Aluno(
        id=uuid4(),
        nome="Kristiano Fernandes Plácido",
        email=f"{uuid4()}@discente.ufma.br",
        matricula=str(uuid4())[:20],
        grupo_experimental=GrupoExperimental.EXPERIMENTAL,
        data_cadastro=datetime.now(UTC),
    )
    await AlunoRepositorySQLAlchemy(session).adicionar(aluno)

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
        aluno_id=aluno.id,
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
        aluno_id=aluno.id,
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


async def _mensagens_do_processamento(
    session: AsyncSession, processamento_id: UUID
) -> list[MensagemFila]:
    consulta = select(MensagemFila).where(MensagemFila.processamento_id == processamento_id)
    return list((await session.execute(consulta)).scalars().all())


async def test_publicar_insere_mensagem_referenciando_o_processamento(
    db_session: AsyncSession,
) -> None:
    processamento = await _criar_processamento(db_session)
    fila = FilaPostgres(db_session)

    await fila.publicar(processamento.id)

    mensagens = await _mensagens_do_processamento(db_session, processamento.id)
    assert len(mensagens) == 1


async def test_publicar_com_processamento_inexistente_levanta_erro_de_integridade(
    db_session: AsyncSession,
) -> None:
    fila = FilaPostgres(db_session)

    with pytest.raises(IntegrityError):
        await fila.publicar(uuid4())


async def test_publicar_isola_mensagens_de_processamentos_diferentes(
    db_session: AsyncSession,
) -> None:
    processamento1 = await _criar_processamento(db_session)
    processamento2 = await _criar_processamento(db_session)
    fila = FilaPostgres(db_session)

    await fila.publicar(processamento1.id)
    await fila.publicar(processamento2.id)

    mensagens1 = await _mensagens_do_processamento(db_session, processamento1.id)
    mensagens2 = await _mensagens_do_processamento(db_session, processamento2.id)
    assert len(mensagens1) == 1
    assert len(mensagens2) == 1
    assert mensagens1[0].id != mensagens2[0].id


async def test_reivindicar_proximo_marca_em_processamento_e_retorna_o_id(
    db_session: AsyncSession,
) -> None:
    processamento = await _criar_processamento(db_session)
    fila = FilaPostgres(db_session)
    await fila.publicar(processamento.id)

    reivindicado = await fila.reivindicar_proximo()

    assert reivindicado == processamento.id
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    atualizado = await repositorio.obter_por_id(processamento.id)
    assert atualizado is not None
    assert atualizado.status == StatusProcessamento.EM_PROCESSAMENTO
    assert atualizado.inicio is not None


async def test_reivindicar_proximo_respeita_a_ordem_de_chegada_na_fila(
    db_session: AsyncSession,
) -> None:
    mais_antigo = await _criar_processamento(db_session)
    mais_novo = await _criar_processamento(db_session)
    fila = FilaPostgres(db_session)
    await fila.publicar(mais_antigo.id)
    await fila.publicar(mais_novo.id)

    reivindicado = await fila.reivindicar_proximo()

    assert reivindicado == mais_antigo.id


async def test_reivindicar_proximo_com_fila_vazia_retorna_none(db_session: AsyncSession) -> None:
    fila = FilaPostgres(db_session)

    assert await fila.reivindicar_proximo() is None


async def test_reivindicar_proximo_ignora_processamento_ja_reivindicado(
    db_session: AsyncSession,
) -> None:
    processamento = await _criar_processamento(db_session)
    fila = FilaPostgres(db_session)
    await fila.publicar(processamento.id)
    await fila.reivindicar_proximo()

    assert await fila.reivindicar_proximo() is None


async def test_remover_apaga_a_mensagem_da_fila(db_session: AsyncSession) -> None:
    processamento = await _criar_processamento(db_session)
    fila = FilaPostgres(db_session)
    await fila.publicar(processamento.id)

    await fila.remover(processamento.id)

    assert await _mensagens_do_processamento(db_session, processamento.id) == []


async def test_falha_de_integridade_ao_publicar_nao_impede_uso_posterior_da_sessao(
    db_session: AsyncSession,
) -> None:
    # Prova empírica do SAVEPOINT (Fase 7, Etapa 5 — Problema 1): uma falha
    # REAL de banco (violação de UniqueConstraint em processamento_id) durante
    # publicar() não pode envenenar a transação — o chamador
    # (CriarProcessamentoUseCase) precisa marcar o Processamento como erro na
    # mesma sessão logo em seguida. Sem o `begin_nested()` em FilaPostgres
    # .publicar(), a chamada a `atualizar()` abaixo levantaria
    # PendingRollbackError em vez de persistir o erro.
    processamento = await _criar_processamento(db_session)
    fila = FilaPostgres(db_session)
    await fila.publicar(processamento.id)

    with pytest.raises(IntegrityError):
        await fila.publicar(processamento.id)

    processamento.marcar_como_erro("Falha ao publicar a solicitação na fila de processamento.")
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    await repositorio.atualizar(processamento)

    atualizado = await repositorio.obter_por_id(processamento.id)
    assert atualizado is not None
    assert atualizado.status == StatusProcessamento.ERRO
    assert atualizado.erro == "Falha ao publicar a solicitação na fila de processamento."


async def test_dois_workers_disputando_a_mesma_mensagem_apenas_um_reivindica() -> None:
    # Concorrência real exige transações/conexões independentes e commitadas —
    # o `db_session` de teste roda tudo numa única transação não commitada,
    # o que não exercitaria o SKIP LOCKED entre sessões distintas.
    async with sessao_transacional() as session:
        processamento = await _criar_processamento(session)
        await FilaPostgres(session).publicar(processamento.id)

    async def _tentar_reivindicar() -> UUID | None:
        async with sessao_transacional() as session:
            return await FilaPostgres(session).reivindicar_proximo()

    resultados = await asyncio.gather(_tentar_reivindicar(), _tentar_reivindicar())

    vencedores = [r for r in resultados if r is not None]
    assert vencedores == [processamento.id]
    assert resultados.count(None) == 1
