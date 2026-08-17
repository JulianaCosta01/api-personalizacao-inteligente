from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.unit.application.material.fakes import ObjectStorageFake
from tests.unit.application.perfil.fakes import LLMFake

from application.processamento.processar_personalizacao import ProcessarPersonalizacaoUseCase
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
from infrastructure.database.material_personalizado.material_personalizado_repository import (
    MaterialPersonalizadoRepositorySQLAlchemy,
)
from infrastructure.database.models.material_personalizado import (
    MaterialPersonalizado as MaterialPersonalizadoModel,
)
from infrastructure.database.perfil.perfil_repository import PerfilRepositorySQLAlchemy
from infrastructure.database.processamento.processamento_repository import (
    ProcessamentoRepositorySQLAlchemy,
)
from infrastructure.database.session import sessao_transacional
from infrastructure.queue.fila_postgres import FilaPostgres
from infrastructure.queue.models import MensagemFila
from worker.claim import reivindicar_processamento
from worker.worker import processar_reivindicado, recuperar_processamentos_presos


async def _semear_processamento(
    status: StatusProcessamento = StatusProcessamento.PENDENTE,
    inicio: datetime | None = None,
) -> tuple[Processamento, MaterialDidatico]:
    async with sessao_transacional() as session:
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
            status=status,
            modelo_ia=None,
            data_criacao=datetime.now(UTC),
            inicio=inicio,
            fim=None,
            erro=None,
        )
        await ProcessamentoRepositorySQLAlchemy(session).adicionar(processamento)
        await FilaPostgres(session).publicar(processamento.id)

    return processamento, material


def _fabrica_com_fakes(
    storage: ObjectStorageFake, llm: LLMFake
) -> Callable[[AsyncSession], ProcessarPersonalizacaoUseCase]:
    def _fabrica(session: AsyncSession) -> ProcessarPersonalizacaoUseCase:
        return ProcessarPersonalizacaoUseCase(
            ProcessamentoRepositorySQLAlchemy(session),
            MaterialRepositorySQLAlchemy(session),
            PerfilRepositorySQLAlchemy(session),
            MaterialPersonalizadoRepositorySQLAlchemy(session),
            storage,
            llm,
        )

    return _fabrica


async def _obter_processamento(processamento_id: UUID) -> Processamento | None:
    async with sessao_transacional() as session:
        return await ProcessamentoRepositorySQLAlchemy(session).obter_por_id(processamento_id)


async def _mensagem_na_fila(processamento_id: UUID) -> bool:
    async with sessao_transacional() as session:
        consulta = select(MensagemFila).where(MensagemFila.processamento_id == processamento_id)
        return (await session.execute(consulta)).scalars().first() is not None


async def _material_personalizado_existe(processamento_id: UUID) -> bool:
    async with sessao_transacional() as session:
        consulta = select(MaterialPersonalizadoModel).where(
            MaterialPersonalizadoModel.processamento_id == processamento_id
        )
        return (await session.execute(consulta)).scalars().first() is not None


async def test_reivindicar_processamento_marca_em_processamento_e_registra_inicio() -> None:
    processamento, _material = await _semear_processamento()

    reivindicado = await reivindicar_processamento()

    assert reivindicado == processamento.id
    atualizado = await _obter_processamento(processamento.id)
    assert atualizado is not None
    assert atualizado.status == StatusProcessamento.EM_PROCESSAMENTO
    assert atualizado.inicio is not None


async def test_processar_reivindicado_com_sucesso_marca_concluido_e_remove_da_fila() -> None:
    processamento, material = await _semear_processamento(
        status=StatusProcessamento.EM_PROCESSAMENTO, inicio=datetime.now(UTC)
    )
    storage = ObjectStorageFake()
    storage.salvos[material.caminho_storage] = b"%PDF-conteudo original"
    llm = LLMFake()

    status_final = await processar_reivindicado(
        processamento.id, fabrica_caso_de_uso=_fabrica_com_fakes(storage, llm)
    )

    assert status_final == StatusProcessamento.CONCLUIDO
    atualizado = await _obter_processamento(processamento.id)
    assert atualizado is not None
    assert atualizado.status == StatusProcessamento.CONCLUIDO
    assert atualizado.erro is None
    assert await _mensagem_na_fila(processamento.id) is False


async def test_processar_reivindicado_com_falha_marca_erro_e_mantem_mensagem_na_fila() -> None:
    processamento, material = await _semear_processamento(
        status=StatusProcessamento.EM_PROCESSAMENTO, inicio=datetime.now(UTC)
    )
    storage = ObjectStorageFake()
    storage.salvos[material.caminho_storage] = b"%PDF-conteudo original"
    llm = LLMFake(retornar_none_na_reescrita=True)

    status_final = await processar_reivindicado(
        processamento.id, fabrica_caso_de_uso=_fabrica_com_fakes(storage, llm)
    )

    assert status_final == StatusProcessamento.ERRO
    atualizado = await _obter_processamento(processamento.id)
    assert atualizado is not None
    assert atualizado.status == StatusProcessamento.ERRO
    assert atualizado.erro is not None
    assert await _mensagem_na_fila(processamento.id) is True


async def test_recuperar_processamentos_presos_devolve_para_pendente() -> None:
    preso, _material = await _semear_processamento(
        status=StatusProcessamento.EM_PROCESSAMENTO,
        inicio=datetime.now(UTC) - timedelta(hours=1),
    )
    recente, _material2 = await _semear_processamento(
        status=StatusProcessamento.EM_PROCESSAMENTO, inicio=datetime.now(UTC)
    )

    liberados = await recuperar_processamentos_presos()

    assert preso.id in liberados
    assert recente.id not in liberados
    preso_atualizado = await _obter_processamento(preso.id)
    recente_atualizado = await _obter_processamento(recente.id)
    assert preso_atualizado is not None
    assert preso_atualizado.status == StatusProcessamento.PENDENTE
    assert recente_atualizado is not None
    assert recente_atualizado.status == StatusProcessamento.EM_PROCESSAMENTO

    # Consome o processamento liberado para não deixar um PENDENTE commitado
    # residual, o que poderia ser reivindicado por outro teste desta suíte.
    assert await reivindicar_processamento() == preso.id


async def test_processamento_liberado_pela_recuperacao_pode_ser_reivindicado_novamente() -> None:
    preso, _material = await _semear_processamento(
        status=StatusProcessamento.EM_PROCESSAMENTO,
        inicio=datetime.now(UTC) - timedelta(hours=1),
    )

    await recuperar_processamentos_presos()
    reivindicado = await reivindicar_processamento()

    assert reivindicado == preso.id


async def test_falha_ao_remover_da_fila_reverte_upload_e_preserva_estado_anterior() -> None:
    """Fase 7, Etapa 5 — Problema 2.

    Simula uma falha real na etapa POSTERIOR ao sucesso do Use Case: a
    remoção da mensagem da fila. O rollback do Postgres (real, não mockado)
    desfaz o MaterialPersonalizado e a marcação de concluído — mas o PDF já
    enviado ao Storage não seria desfeito por esse rollback. A correção faz
    o Worker reverter esse upload explicitamente antes de propagar o erro.
    """
    processamento, material = await _semear_processamento(
        status=StatusProcessamento.EM_PROCESSAMENTO, inicio=datetime.now(UTC)
    )
    storage = ObjectStorageFake()
    storage.salvos[material.caminho_storage] = b"%PDF-conteudo original"
    llm = LLMFake()

    with (
        patch(
            "infrastructure.queue.fila_postgres.FilaPostgres.remover",
            new=AsyncMock(side_effect=RuntimeError("falha simulada ao remover da fila")),
        ),
        pytest.raises(RuntimeError, match="falha simulada ao remover da fila"),
    ):
        await processar_reivindicado(
            processamento.id, fabrica_caso_de_uso=_fabrica_com_fakes(storage, llm)
        )

    # 1. O processamento NÃO fica falsamente concluído — a transação inteira
    #    (real, Postgres) foi desfeita, permanecendo como estava antes.
    atualizado = await _obter_processamento(processamento.id)
    assert atualizado is not None
    assert atualizado.status == StatusProcessamento.EM_PROCESSAMENTO
    assert atualizado.erro is None

    # 2. A mensagem da fila permanece disponível (nunca chegou a ser
    #    removida de fato, e o rollback também desfaria a remoção se tivesse).
    assert await _mensagem_na_fila(processamento.id) is True

    # 3. MaterialPersonalizado não fica persistido indevidamente.
    assert await _material_personalizado_existe(processamento.id) is False

    # 4. O PDF gerado é removido do Storage (reverter_upload executado) — e
    #    não o PDF original do Material, que nunca deveria ser tocado.
    assert len(storage.removidos) == 1
    assert material.caminho_storage not in storage.removidos


async def test_falha_no_cleanup_apos_falha_na_remocao_da_fila_nao_esconde_erro_original() -> None:
    """Se o próprio cleanup do Storage falhar, o erro ORIGINAL (falha ao
    remover da fila) continua sendo o que se propaga — reverter_upload já
    é projetado para nunca mascarar a causa raiz (Etapa 3), e essa garantia
    precisa continuar valendo quando acionado a partir do Worker."""
    processamento, material = await _semear_processamento(
        status=StatusProcessamento.EM_PROCESSAMENTO, inicio=datetime.now(UTC)
    )
    storage = ObjectStorageFake(falhar_remocao=True)
    storage.salvos[material.caminho_storage] = b"%PDF-conteudo original"
    llm = LLMFake()

    with (
        patch(
            "infrastructure.queue.fila_postgres.FilaPostgres.remover",
            new=AsyncMock(side_effect=RuntimeError("falha simulada ao remover da fila")),
        ),
        pytest.raises(RuntimeError, match="falha simulada ao remover da fila"),
    ):
        await processar_reivindicado(
            processamento.id, fabrica_caso_de_uso=_fabrica_com_fakes(storage, llm)
        )

    # O rollback real do banco continua acontecendo independentemente do
    # cleanup do Storage ter ou não sucesso.
    atualizado = await _obter_processamento(processamento.id)
    assert atualizado is not None
    assert atualizado.status == StatusProcessamento.EM_PROCESSAMENTO
