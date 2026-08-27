from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo
from domain.material_personalizado.material_personalizado import MaterialPersonalizado
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
        status=StatusProcessamento.EM_PROCESSAMENTO,
        modelo_ia="gemini-3.1-flash-lite",
        data_criacao=datetime.now(UTC),
        inicio=datetime.now(UTC),
        fim=None,
        erro=None,
    )
    await ProcessamentoRepositorySQLAlchemy(session).adicionar(processamento)
    return processamento


def _material_personalizado(processamento_id: UUID) -> MaterialPersonalizado:
    return MaterialPersonalizado(
        id=uuid4(),
        processamento_id=processamento_id,
        titulo="Introdução a Grafos (Personalizado)",
        caminho_pdf=f"materiais-personalizados/{uuid4()}.pdf",
        resumo="Resumo do material adaptado ao estilo do aluno.",
        data_geracao=datetime.now(UTC),
    )


async def test_adiciona_e_persiste_material_personalizado(db_session: AsyncSession) -> None:
    processamento = await _criar_processamento(db_session)
    repositorio = MaterialPersonalizadoRepositorySQLAlchemy(db_session)
    material_personalizado = _material_personalizado(processamento.id)

    await repositorio.adicionar(material_personalizado)

    persistido = await db_session.get(MaterialPersonalizadoModel, material_personalizado.id)
    assert persistido is not None
    assert persistido.processamento_id == processamento.id
    assert persistido.titulo == material_personalizado.titulo
    assert persistido.caminho_pdf == material_personalizado.caminho_pdf
    assert persistido.resumo == material_personalizado.resumo


async def test_adiciona_e_obtem_por_id(db_session: AsyncSession) -> None:
    processamento = await _criar_processamento(db_session)
    repositorio = MaterialPersonalizadoRepositorySQLAlchemy(db_session)
    material_personalizado = _material_personalizado(processamento.id)

    await repositorio.adicionar(material_personalizado)
    encontrado = await repositorio.obter_por_id(material_personalizado.id)

    assert encontrado is not None
    assert encontrado.processamento_id == processamento.id
    assert encontrado.titulo == material_personalizado.titulo


async def test_obter_por_id_inexistente_retorna_none(db_session: AsyncSession) -> None:
    repositorio = MaterialPersonalizadoRepositorySQLAlchemy(db_session)

    assert await repositorio.obter_por_id(uuid4()) is None


async def test_obtem_por_processamento_id(db_session: AsyncSession) -> None:
    processamento = await _criar_processamento(db_session)
    repositorio = MaterialPersonalizadoRepositorySQLAlchemy(db_session)
    material_personalizado = _material_personalizado(processamento.id)
    await repositorio.adicionar(material_personalizado)

    encontrado = await repositorio.obter_por_processamento_id(processamento.id)

    assert encontrado is not None
    assert encontrado.id == material_personalizado.id


async def test_obter_por_processamento_id_inexistente_retorna_none(
    db_session: AsyncSession,
) -> None:
    repositorio = MaterialPersonalizadoRepositorySQLAlchemy(db_session)

    assert await repositorio.obter_por_processamento_id(uuid4()) is None


async def test_adicionar_com_processamento_inexistente_levanta_erro_de_integridade(
    db_session: AsyncSession,
) -> None:
    repositorio = MaterialPersonalizadoRepositorySQLAlchemy(db_session)

    with pytest.raises(IntegrityError):
        await repositorio.adicionar(_material_personalizado(uuid4()))


async def test_processamento_id_e_unico_por_material_personalizado(
    db_session: AsyncSession,
) -> None:
    processamento = await _criar_processamento(db_session)
    repositorio = MaterialPersonalizadoRepositorySQLAlchemy(db_session)
    await repositorio.adicionar(_material_personalizado(processamento.id))

    with pytest.raises(IntegrityError):
        await repositorio.adicionar(_material_personalizado(processamento.id))


async def test_falha_de_integridade_nao_impede_uso_posterior_da_sessao(
    db_session: AsyncSession,
) -> None:
    # Prova empírica do SAVEPOINT (Fase 7, Etapa 5 — Problema 1): uma falha
    # REAL de banco (violação de UniqueConstraint em processamento_id) durante
    # adicionar() não pode envenenar a transação — o chamador
    # (ProcessarPersonalizacaoUseCase) precisa marcar o Processamento como
    # erro na mesma sessão logo em seguida. Sem o `begin_nested()` em
    # MaterialPersonalizadoRepositorySQLAlchemy.adicionar(), a chamada a
    # `atualizar()` abaixo levantaria PendingRollbackError em vez de
    # persistir o erro.
    processamento = await _criar_processamento(db_session)
    repositorio = MaterialPersonalizadoRepositorySQLAlchemy(db_session)
    await repositorio.adicionar(_material_personalizado(processamento.id))

    with pytest.raises(IntegrityError):
        await repositorio.adicionar(_material_personalizado(processamento.id))

    processamento.marcar_como_erro("Falha ao processar a personalização do material.")
    processamento_repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    await processamento_repositorio.atualizar(processamento)

    atualizado = await processamento_repositorio.obter_por_id(processamento.id)
    assert atualizado is not None
    assert atualizado.status == StatusProcessamento.ERRO
    assert atualizado.erro == "Falha ao processar a personalização do material."
