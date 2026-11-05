from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from application.ports.llm import CategoriaFalhaTransitoria, FalhaTransitoriaDoProvedorError
from application.processamento.politica_de_repeticao import PoliticaDeRepeticao
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
from infrastructure.database.models.processamento import Processamento as ProcessamentoModel
from infrastructure.database.perfil.perfil_repository import PerfilRepositorySQLAlchemy
from infrastructure.database.processamento.processamento_repository import (
    ProcessamentoRepositorySQLAlchemy,
)
from infrastructure.database.session import sessao_transacional
from infrastructure.queue.fila_postgres import FilaPostgres
from infrastructure.queue.models import MensagemFila
from tests.unit.application.material.fakes import ObjectStorageFake
from tests.unit.application.perfil.fakes import LLMFake
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
    storage: ObjectStorageFake, llm: LLMFake, politica: PoliticaDeRepeticao | None = None
) -> Callable[[AsyncSession], ProcessarPersonalizacaoUseCase]:
    def _fabrica(session: AsyncSession) -> ProcessarPersonalizacaoUseCase:
        return ProcessarPersonalizacaoUseCase(
            ProcessamentoRepositorySQLAlchemy(session),
            MaterialRepositorySQLAlchemy(session),
            PerfilRepositorySQLAlchemy(session),
            MaterialPersonalizadoRepositorySQLAlchemy(session),
            storage,
            llm,
            politica,
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
    """Simula falha na remoção da fila após o sucesso do Use Case: o rollback do Postgres
    desfaz o registro, mas não o PDF já enviado ao Storage: o Worker reverte esse upload à parte.
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

    # O processamento não fica falsamente concluído: a transação real (Postgres)
    # foi desfeita, permanecendo como estava antes.
    atualizado = await _obter_processamento(processamento.id)
    assert atualizado is not None
    assert atualizado.status == StatusProcessamento.EM_PROCESSAMENTO
    assert atualizado.erro is None

    # A mensagem da fila permanece disponível: nunca chegou a ser removida de fato.
    assert await _mensagem_na_fila(processamento.id) is True

    # MaterialPersonalizado não fica persistido indevidamente.
    assert await _material_personalizado_existe(processamento.id) is False

    # O PDF gerado é removido do Storage (reverter_upload), nunca o PDF original do Material.
    assert len(storage.removidos) == 1
    assert material.caminho_storage not in storage.removidos


async def test_falha_no_cleanup_apos_falha_na_remocao_da_fila_nao_esconde_erro_original() -> None:
    """Se o cleanup do Storage falhar, o erro original (falha ao remover da
    fila) continua sendo o que se propaga: reverter_upload nunca mascara a causa raiz."""
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


async def _expirar_espera(processamento_id: UUID) -> None:
    async with sessao_transacional() as session:
        await session.execute(
            update(ProcessamentoModel)
            .where(ProcessamentoModel.id == processamento_id)
            .values(disponivel_em=datetime.now(UTC) - timedelta(seconds=1))
        )


@pytest_asyncio.fixture
async def semeados_para_limpeza() -> AsyncGenerator[list[UUID]]:
    """Garante, mesmo se o teste falhar no meio, que nenhum processamento semeado fique
    `pendente` (reivindicável por outro teste desta suíte) nem com mensagem residual.

    Os testes do Worker precisam de estado commitado (várias sessões), então o rollback do
    `db_session` não serve; a limpeza é explícita e só atinge os ids registrados pelo teste.
    """
    ids: list[UUID] = []
    yield ids
    async with sessao_transacional() as session:
        await session.execute(
            update(ProcessamentoModel)
            .where(ProcessamentoModel.id.in_(ids))
            .where(ProcessamentoModel.status == StatusProcessamento.PENDENTE.value)
            .values(
                status=StatusProcessamento.ERRO.value,
                erro="Encerrado pela limpeza do teste.",
                disponivel_em=None,
            )
        )
        await session.execute(delete(MensagemFila).where(MensagemFila.processamento_id.in_(ids)))


async def _reivindicavel_sem_efeito(db_session: AsyncSession) -> UUID | None:
    """Quem o claim escolheria agora, SEM reivindicar de verdade.

    O `db_session` faz rollback no fim do teste: o UPDATE do claim não é commitado, então nada é
    consumido nem alterado. Não pressupõe banco vazio: o chamador só afirma que o processamento
    que ele testa não é o escolhido.
    """
    return await FilaPostgres(db_session).reivindicar_proximo()


def _llm_com_falha_transitoria() -> LLMFake:
    return LLMFake(
        falha_transitoria_na_reescrita=FalhaTransitoriaDoProvedorError(
            CategoriaFalhaTransitoria.HTTP_5XX, 503
        )
    )


async def test_falha_transitoria_devolve_o_job_a_pendente_com_espera_e_mantem_a_mensagem(
    db_session: AsyncSession, semeados_para_limpeza: list[UUID]
) -> None:
    processamento, material = await _semear_processamento()
    semeados_para_limpeza.append(processamento.id)
    storage = ObjectStorageFake()
    storage.salvos[material.caminho_storage] = b"%PDF-conteudo original"
    assert await reivindicar_processamento() == processamento.id

    status = await processar_reivindicado(
        processamento.id,
        fabrica_caso_de_uso=_fabrica_com_fakes(
            storage, _llm_com_falha_transitoria(), PoliticaDeRepeticao(3)
        ),
    )

    assert status == StatusProcessamento.PENDENTE
    gravado = await _obter_processamento(processamento.id)
    assert gravado is not None
    assert gravado.status == StatusProcessamento.PENDENTE
    assert gravado.tentativas == 1
    assert gravado.disponivel_em is not None and gravado.disponivel_em > datetime.now(UTC)
    assert gravado.fim is None and gravado.erro is None
    assert await _mensagem_na_fila(processamento.id) is True
    assert await _material_personalizado_existe(processamento.id) is False
    # Em espera: não pode ser reivindicado de novo antes do horário (verificação sem efeito).
    assert await _reivindicavel_sem_efeito(db_session) != processamento.id


async def test_falha_transitoria_persistente_termina_em_erro_exatamente_no_limite(
    db_session: AsyncSession, semeados_para_limpeza: list[UUID]
) -> None:
    processamento, material = await _semear_processamento()
    semeados_para_limpeza.append(processamento.id)
    storage = ObjectStorageFake()
    storage.salvos[material.caminho_storage] = b"%PDF-conteudo original"
    fabrica = _fabrica_com_fakes(storage, _llm_com_falha_transitoria(), PoliticaDeRepeticao(3))

    for tentativa in (1, 2, 3):
        if tentativa > 1:
            await _expirar_espera(processamento.id)
        assert await reivindicar_processamento() == processamento.id
        status = await processar_reivindicado(processamento.id, fabrica_caso_de_uso=fabrica)
        esperado = StatusProcessamento.PENDENTE if tentativa < 3 else StatusProcessamento.ERRO
        assert status == esperado

    final = await _obter_processamento(processamento.id)
    assert final is not None
    assert final.status == StatusProcessamento.ERRO
    assert final.tentativas == 3  # o limite nunca é ultrapassado
    assert final.erro == "Falha ao processar a personalização do material."
    assert await _material_personalizado_existe(processamento.id) is False
    # Encerrado em erro: não volta à fila, mesmo com a mensagem ainda registrada (como antes).
    await _expirar_espera(processamento.id)
    assert await _reivindicavel_sem_efeito(db_session) != processamento.id


async def test_falha_transitoria_seguida_de_sucesso_conclui_sem_duplicar_o_material(
    db_session: AsyncSession, semeados_para_limpeza: list[UUID]
) -> None:
    processamento, material = await _semear_processamento()
    semeados_para_limpeza.append(processamento.id)
    storage = ObjectStorageFake()
    storage.salvos[material.caminho_storage] = b"%PDF-conteudo original"
    politica = PoliticaDeRepeticao(3)

    assert await reivindicar_processamento() == processamento.id
    assert (
        await processar_reivindicado(
            processamento.id,
            fabrica_caso_de_uso=_fabrica_com_fakes(storage, _llm_com_falha_transitoria(), politica),
        )
        == StatusProcessamento.PENDENTE
    )

    await _expirar_espera(processamento.id)
    assert await reivindicar_processamento() == processamento.id
    status = await processar_reivindicado(
        processamento.id, fabrica_caso_de_uso=_fabrica_com_fakes(storage, LLMFake(), politica)
    )

    assert status == StatusProcessamento.CONCLUIDO
    final = await _obter_processamento(processamento.id)
    assert final is not None and final.status == StatusProcessamento.CONCLUIDO
    assert final.tentativas == 2
    assert await _material_personalizado_existe(processamento.id) is True
    assert await _mensagem_na_fila(processamento.id) is False  # concluído remove a mensagem
    # Concluído não é reivindicado de novo (verificação sem efeito).
    assert await _reivindicavel_sem_efeito(db_session) != processamento.id
