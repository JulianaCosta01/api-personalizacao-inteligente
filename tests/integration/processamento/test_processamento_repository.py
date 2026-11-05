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
from infrastructure.database.models.processamento import Processamento as ProcessamentoModel
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


# Posse da execução e tentativas


async def test_atualizar_se_dono_grava_quando_a_reivindicacao_e_a_mesma(
    db_session: AsyncSession,
) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    em_execucao = _processamento_em_processamento(
        aluno.id, material.id, perfil.id, datetime.now(UTC) - timedelta(minutes=1)
    )
    await repositorio.adicionar(em_execucao)

    em_execucao.marcar_como_concluido()
    assert await repositorio.atualizar_se_dono(em_execucao) is True

    gravado = await repositorio.obter_por_id(em_execucao.id)
    assert gravado is not None and gravado.status == StatusProcessamento.CONCLUIDO
    assert gravado.fim is not None


async def test_atualizar_se_dono_nao_grava_se_o_processamento_ja_foi_concluido(
    db_session: AsyncSession,
) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    inicio = datetime.now(UTC) - timedelta(minutes=1)
    concluido = _processamento_em_processamento(aluno.id, material.id, perfil.id, inicio)
    await repositorio.adicionar(concluido)
    concluido.marcar_como_concluido()
    assert await repositorio.atualizar_se_dono(concluido) is True

    # Uma segunda execução (que já perdeu a posse) tenta registrar erro sobre o estado concluído.
    retardatario = _processamento_em_processamento(aluno.id, material.id, perfil.id, inicio)
    retardatario.id = concluido.id
    retardatario.marcar_como_erro("tardio")

    assert await repositorio.atualizar_se_dono(retardatario) is False
    gravado = await repositorio.obter_por_id(concluido.id)
    assert gravado is not None and gravado.status == StatusProcessamento.CONCLUIDO
    assert gravado.erro is None


async def test_atualizar_se_dono_nao_grava_se_outra_reivindicacao_assumiu(
    db_session: AsyncSession,
) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    inicio_antigo = datetime.now(UTC) - timedelta(minutes=30)
    original = _processamento_em_processamento(aluno.id, material.id, perfil.id, inicio_antigo)
    await repositorio.adicionar(original)

    # A recuperação devolve à fila e uma nova reivindicação grava um `inicio` mais novo.
    modelo = await db_session.get(ProcessamentoModel, original.id)
    assert modelo is not None
    modelo.inicio = datetime.now(UTC)
    await db_session.flush()

    original.marcar_como_concluido()  # a execução antiga termina tarde, com o `inicio` antigo
    assert await repositorio.atualizar_se_dono(original) is False
    await db_session.refresh(modelo)
    assert modelo.status == StatusProcessamento.EM_PROCESSAMENTO.value


async def test_esgotar_tentativas_encerra_em_erro_e_liberar_nao_devolve_esse_job(
    db_session: AsyncSession,
) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    antigo = datetime.now(UTC) - timedelta(minutes=20)
    esgotado = _processamento_em_processamento(aluno.id, material.id, perfil.id, antigo)
    esgotado.tentativas = 3
    com_tentativas = _processamento_em_processamento(aluno.id, material.id, perfil.id, antigo)
    com_tentativas.tentativas = 1
    await repositorio.adicionar(esgotado)
    await repositorio.adicionar(com_tentativas)

    encerrados = await repositorio.esgotar_tentativas_dos_presos(timedelta(minutes=10), 3)
    liberados = await repositorio.liberar_presos(timedelta(minutes=10), 3)

    assert encerrados == [esgotado.id]
    assert liberados == [com_tentativas.id]
    final = await repositorio.obter_por_id(esgotado.id)
    assert final is not None and final.status == StatusProcessamento.ERRO
    assert final.fim is not None and final.erro is not None
    outro = await repositorio.obter_por_id(com_tentativas.id)
    assert outro is not None and outro.status == StatusProcessamento.PENDENTE


async def test_devolver_para_fila_se_dono_volta_a_pendente_com_espera(
    db_session: AsyncSession,
) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    em_execucao = _processamento_em_processamento(
        aluno.id, material.id, perfil.id, datetime.now(UTC) - timedelta(seconds=30)
    )
    em_execucao.tentativas = 1
    await repositorio.adicionar(em_execucao)
    espera = datetime.now(UTC) + timedelta(seconds=30)

    assert await repositorio.devolver_para_fila_se_dono(em_execucao, espera, 3) is True

    gravado = await repositorio.obter_por_id(em_execucao.id)
    assert gravado is not None
    assert gravado.status == StatusProcessamento.PENDENTE
    assert gravado.disponivel_em == espera
    assert gravado.tentativas == 1  # o contador só sobe na reivindicação
    assert gravado.fim is None and gravado.erro is None


@pytest.mark.parametrize("tentativas", [3, 4])
async def test_devolver_para_fila_nao_ultrapassa_o_limite_de_tentativas(
    db_session: AsyncSession, tentativas: int
) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    esgotado = _processamento_em_processamento(
        aluno.id, material.id, perfil.id, datetime.now(UTC) - timedelta(seconds=30)
    )
    esgotado.tentativas = tentativas
    await repositorio.adicionar(esgotado)

    devolvido = await repositorio.devolver_para_fila_se_dono(
        esgotado, datetime.now(UTC) + timedelta(seconds=30), 3
    )

    assert devolvido is False
    gravado = await repositorio.obter_por_id(esgotado.id)
    assert gravado is not None and gravado.status == StatusProcessamento.EM_PROCESSAMENTO
    assert gravado.disponivel_em is None


async def test_devolver_para_fila_nao_grava_se_outra_reivindicacao_assumiu(
    db_session: AsyncSession,
) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    original = _processamento_em_processamento(
        aluno.id, material.id, perfil.id, datetime.now(UTC) - timedelta(minutes=30)
    )
    original.tentativas = 1
    await repositorio.adicionar(original)
    modelo = await db_session.get(ProcessamentoModel, original.id)
    assert modelo is not None
    modelo.inicio = datetime.now(UTC)  # outra reivindicação com `inicio` mais novo
    await db_session.flush()

    devolvido = await repositorio.devolver_para_fila_se_dono(
        original, datetime.now(UTC) + timedelta(seconds=30), 3
    )

    assert devolvido is False
    await db_session.refresh(modelo)
    assert modelo.status == StatusProcessamento.EM_PROCESSAMENTO.value
    assert modelo.disponivel_em is None


@pytest.mark.parametrize("estado", [StatusProcessamento.CONCLUIDO, StatusProcessamento.ERRO])
async def test_devolver_para_fila_nunca_reabre_job_encerrado(
    db_session: AsyncSession, estado: StatusProcessamento
) -> None:
    aluno, material, perfil = await _cadeia_completa(db_session)
    repositorio = ProcessamentoRepositorySQLAlchemy(db_session)
    inicio = datetime.now(UTC) - timedelta(minutes=1)
    encerrado = _processamento_em_processamento(aluno.id, material.id, perfil.id, inicio)
    encerrado.tentativas = 1
    await repositorio.adicionar(encerrado)
    if estado == StatusProcessamento.CONCLUIDO:
        encerrado.marcar_como_concluido()
    else:
        encerrado.marcar_como_erro("definitivo")
    assert await repositorio.atualizar_se_dono(encerrado) is True

    retardatario = _processamento_em_processamento(aluno.id, material.id, perfil.id, inicio)
    retardatario.id = encerrado.id
    retardatario.tentativas = 1

    assert (
        await repositorio.devolver_para_fila_se_dono(
            retardatario, datetime.now(UTC) + timedelta(seconds=30), 3
        )
        is False
    )
    gravado = await repositorio.obter_por_id(encerrado.id)
    assert gravado is not None and gravado.status == estado
