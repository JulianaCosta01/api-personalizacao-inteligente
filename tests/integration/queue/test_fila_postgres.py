import asyncio
from datetime import UTC, datetime, timedelta
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
from infrastructure.database.models.processamento import Processamento as ProcessamentoModel
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
    # Prova o SAVEPOINT: uma falha real de banco em publicar() não pode envenenar a
    # transação; sem begin_nested(), atualizar() abaixo levantaria PendingRollbackError.
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
    # Concorrência real exige transações/conexões independentes e commitadas; o `db_session`
    # de teste roda numa só transação não commitada, sem exercitar o SKIP LOCKED entre sessões.
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


async def test_reivindicar_proximo_incrementa_o_contador_de_tentativas(
    db_session: AsyncSession,
) -> None:
    processamento = await _criar_processamento(db_session)
    fila = FilaPostgres(db_session)
    await fila.publicar(processamento.id)

    reivindicado = await fila.reivindicar_proximo()

    assert reivindicado == processamento.id
    modelo = await db_session.get(ProcessamentoModel, processamento.id)
    assert modelo is not None
    await db_session.refresh(modelo)
    assert modelo.tentativas == 1


# Espera entre tentativas (disponivel_em) e job devolvido à fila


async def _definir_disponivel_em(
    session: AsyncSession, processamento_id: UUID, quando: datetime | None
) -> None:
    modelo = await session.get(ProcessamentoModel, processamento_id)
    assert modelo is not None
    modelo.disponivel_em = quando
    await session.flush()


async def test_reivindicar_proximo_ignora_pendente_com_espera_no_futuro(
    db_session: AsyncSession,
) -> None:
    processamento = await _criar_processamento(db_session)
    fila = FilaPostgres(db_session)
    await fila.publicar(processamento.id)
    await _definir_disponivel_em(
        db_session, processamento.id, datetime.now(UTC) + timedelta(hours=1)
    )

    assert await fila.reivindicar_proximo() is None


async def test_reivindicar_proximo_aceita_pendente_com_espera_vencida_e_zera_a_espera(
    db_session: AsyncSession,
) -> None:
    processamento = await _criar_processamento(db_session)
    fila = FilaPostgres(db_session)
    await fila.publicar(processamento.id)
    await _definir_disponivel_em(
        db_session, processamento.id, datetime.now(UTC) - timedelta(seconds=1)
    )

    assert await fila.reivindicar_proximo() == processamento.id

    modelo = await db_session.get(ProcessamentoModel, processamento.id)
    assert modelo is not None
    await db_session.refresh(modelo)
    assert modelo.disponivel_em is None


async def test_job_em_espera_nao_bloqueia_o_proximo_da_fila(db_session: AsyncSession) -> None:
    em_espera = await _criar_processamento(db_session)
    seguinte = await _criar_processamento(db_session)
    fila = FilaPostgres(db_session)
    await fila.publicar(em_espera.id)
    await fila.publicar(seguinte.id)
    await _definir_disponivel_em(db_session, em_espera.id, datetime.now(UTC) + timedelta(hours=1))

    assert await fila.reivindicar_proximo() == seguinte.id


@pytest.mark.parametrize("estado", [StatusProcessamento.CONCLUIDO, StatusProcessamento.ERRO])
async def test_job_encerrado_nunca_volta_a_ser_reivindicado(
    db_session: AsyncSession, estado: StatusProcessamento
) -> None:
    processamento = await _criar_processamento(db_session)
    fila = FilaPostgres(db_session)
    await fila.publicar(processamento.id)  # a mensagem permanece (o claim só olha o status)
    modelo = await db_session.get(ProcessamentoModel, processamento.id)
    assert modelo is not None
    modelo.status = estado.value
    await db_session.flush()

    assert await fila.reivindicar_proximo() is None


async def test_ciclo_completo_de_devolucao_preserva_a_mensagem_e_conta_as_tentativas(
    db_session: AsyncSession,
) -> None:
    processamento = await _criar_processamento(db_session)
    fila = FilaPostgres(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    await fila.publicar(processamento.id)

    assert await fila.reivindicar_proximo() == processamento.id  # tentativa 1
    reivindicado = await repositorio.obter_por_id(processamento.id)
    assert reivindicado is not None and reivindicado.tentativas == 1
    espera = datetime.now(UTC) + timedelta(hours=1)
    assert await repositorio.devolver_para_fila_se_dono(reivindicado, espera, 3) is True

    # Em espera: não é candidato, mas a mensagem da fila segue intacta (sem órfão nem perda).
    assert await fila.reivindicar_proximo() is None
    assert len(await _mensagens_do_processamento(db_session, processamento.id)) == 1

    await _definir_disponivel_em(
        db_session, processamento.id, datetime.now(UTC) - timedelta(seconds=1)
    )
    assert await fila.reivindicar_proximo() == processamento.id  # tentativa 2
    modelo = await db_session.get(ProcessamentoModel, processamento.id)
    assert modelo is not None
    await db_session.refresh(modelo)
    assert modelo.tentativas == 2
    assert modelo.status == StatusProcessamento.EM_PROCESSAMENTO.value
