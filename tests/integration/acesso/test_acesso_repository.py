from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.acesso.acesso_material_personalizado import AcessoMaterialPersonalizado
from domain.acesso.status_leitura import StatusLeitura
from domain.aluno.aluno import Aluno
from domain.aluno.grupo_experimental import GrupoExperimental
from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo
from domain.material_personalizado.material_personalizado import MaterialPersonalizado
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.perfil.perfil import Perfil
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from infrastructure.database.acesso.acesso_repository import AcessoRepositorySQLAlchemy
from infrastructure.database.aluno.aluno_repository import AlunoRepositorySQLAlchemy
from infrastructure.database.material.material_repository import MaterialRepositorySQLAlchemy
from infrastructure.database.material_personalizado.material_personalizado_repository import (
    MaterialPersonalizadoRepositorySQLAlchemy,
)
from infrastructure.database.perfil.perfil_repository import PerfilRepositorySQLAlchemy
from infrastructure.database.processamento.processamento_repository import (
    ProcessamentoRepositorySQLAlchemy,
)


async def _criar_material_personalizado(
    session: AsyncSession,
) -> tuple[Aluno, MaterialPersonalizado]:
    aluno = Aluno(
        id=uuid4(),
        nome="Kristiano Fernandes Plácido",
        email=f"{uuid4()}@discente.ufma.br",
        matricula=str(uuid4())[:20],
        grupo_experimental=GrupoExperimental.EXPERIMENTAL,
        data_cadastro=datetime.now(UTC),
    )
    await AlunoRepositorySQLAlchemy(session).adicionar(aluno)

    material_didatico = MaterialDidatico(
        id=uuid4(),
        titulo="Introdução a Grafos",
        nome_arquivo=f"{uuid4()}.pdf",
        tipo_arquivo=TipoArquivo.PDF,
        caminho_storage=f"materiais/{uuid4()}.pdf",
        versao=1,
        data_upload=datetime.now(UTC),
    )
    await MaterialRepositorySQLAlchemy(session).adicionar(material_didatico)

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
        material_didatico_id=material_didatico.id,
        perfil_id=perfil.id,
        status=StatusProcessamento.CONCLUIDO,
        modelo_ia="gemini-3.1-flash-lite",
        data_criacao=datetime.now(UTC),
        inicio=datetime.now(UTC),
        fim=datetime.now(UTC),
        erro=None,
    )
    await ProcessamentoRepositorySQLAlchemy(session).adicionar(processamento)

    material_personalizado = MaterialPersonalizado(
        id=uuid4(),
        processamento_id=processamento.id,
        titulo="Introdução a Grafos (Personalizado)",
        caminho_pdf=f"materiais-personalizados/{uuid4()}.pdf",
        resumo="Resumo do material adaptado ao estilo do aluno.",
        data_geracao=datetime.now(UTC),
    )
    await MaterialPersonalizadoRepositorySQLAlchemy(session).adicionar(material_personalizado)

    return aluno, material_personalizado


def _acesso(
    material_personalizado_id: UUID,
    aluno_id: UUID,
    porcentagem_leitura: float = 0.5,
) -> AcessoMaterialPersonalizado:
    agora = datetime.now(UTC)
    return AcessoMaterialPersonalizado(
        id=uuid4(),
        material_personalizado_id=material_personalizado_id,
        aluno_id=aluno_id,
        data_primeiro_acesso=agora,
        data_ultimo_acesso=agora,
        tempo_total_leitura=60,
        quantidade_acessos=1,
        porcentagem_leitura=porcentagem_leitura,
        download_realizado=False,
        status_leitura=StatusLeitura.EM_ANDAMENTO,
    )


async def test_adiciona_e_obtem_por_material_personalizado_id_e_aluno_id(
    db_session: AsyncSession,
) -> None:
    aluno, material_personalizado = await _criar_material_personalizado(db_session)
    repositorio = AcessoRepositorySQLAlchemy(db_session)
    acesso = _acesso(material_personalizado.id, aluno.id)

    await repositorio.adicionar(acesso)
    encontrado = await repositorio.obter_por_material_personalizado_id_e_aluno_id(
        material_personalizado.id, aluno.id
    )

    assert encontrado is not None
    assert encontrado.id == acesso.id
    assert encontrado.aluno_id == aluno.id
    assert encontrado.status_leitura == StatusLeitura.EM_ANDAMENTO


async def test_porcentagem_leitura_e_devolvida_como_float_nos_limites_exatos(
    db_session: AsyncSession,
) -> None:
    # Só contra o driver assíncrono real (asyncpg) se pega uma regressão em que Numeric(5, 4)
    # volte como Decimal em vez de float, quebrando a comparação em StatusLeitura no Domínio.
    aluno, material_personalizado = await _criar_material_personalizado(db_session)
    repositorio = AcessoRepositorySQLAlchemy(db_session)
    acesso = _acesso(material_personalizado.id, aluno.id, porcentagem_leitura=1.0)
    await repositorio.adicionar(acesso)

    encontrado = await repositorio.obter_por_material_personalizado_id_e_aluno_id(
        material_personalizado.id, aluno.id
    )

    assert encontrado is not None
    assert type(encontrado.porcentagem_leitura) is float
    assert encontrado.porcentagem_leitura == 1.0


async def test_obter_por_material_personalizado_id_e_aluno_id_inexistente_retorna_none(
    db_session: AsyncSession,
) -> None:
    repositorio = AcessoRepositorySQLAlchemy(db_session)

    assert (
        await repositorio.obter_por_material_personalizado_id_e_aluno_id(uuid4(), uuid4()) is None
    )


async def test_obter_por_material_personalizado_id(db_session: AsyncSession) -> None:
    aluno, material_personalizado = await _criar_material_personalizado(db_session)
    repositorio = AcessoRepositorySQLAlchemy(db_session)
    acesso = _acesso(material_personalizado.id, aluno.id)
    await repositorio.adicionar(acesso)

    encontrado = await repositorio.obter_por_material_personalizado_id(material_personalizado.id)

    assert encontrado is not None
    assert encontrado.id == acesso.id


async def test_obter_por_material_personalizado_id_inexistente_retorna_none(
    db_session: AsyncSession,
) -> None:
    repositorio = AcessoRepositorySQLAlchemy(db_session)

    assert await repositorio.obter_por_material_personalizado_id(uuid4()) is None


async def test_atualizar_persiste_metricas_e_status_leitura(db_session: AsyncSession) -> None:
    aluno, material_personalizado = await _criar_material_personalizado(db_session)
    repositorio = AcessoRepositorySQLAlchemy(db_session)
    acesso = _acesso(material_personalizado.id, aluno.id)
    await repositorio.adicionar(acesso)

    acesso.registrar_acesso(
        tempo_leitura_incremento_segundos=120,
        porcentagem_leitura=1.0,
        download_realizado=True,
    )
    await repositorio.atualizar(acesso)

    encontrado = await repositorio.obter_por_material_personalizado_id_e_aluno_id(
        material_personalizado.id, aluno.id
    )
    assert encontrado is not None
    assert encontrado.quantidade_acessos == 2
    assert encontrado.tempo_total_leitura == 180
    assert encontrado.download_realizado is True
    assert encontrado.status_leitura == StatusLeitura.CONCLUIDO


async def test_atualizar_acesso_inexistente_levanta_lookup_error(db_session: AsyncSession) -> None:
    aluno, material_personalizado = await _criar_material_personalizado(db_session)
    repositorio = AcessoRepositorySQLAlchemy(db_session)

    with pytest.raises(LookupError):
        await repositorio.atualizar(_acesso(material_personalizado.id, aluno.id))


async def test_adicionar_com_material_personalizado_inexistente_levanta_erro_de_integridade(
    db_session: AsyncSession,
) -> None:
    _, material_personalizado = await _criar_material_personalizado(db_session)
    repositorio = AcessoRepositorySQLAlchemy(db_session)

    with pytest.raises(IntegrityError):
        await repositorio.adicionar(_acesso(uuid4(), uuid4()))


async def test_par_material_personalizado_id_aluno_id_e_unico(db_session: AsyncSession) -> None:
    aluno, material_personalizado = await _criar_material_personalizado(db_session)
    repositorio = AcessoRepositorySQLAlchemy(db_session)
    await repositorio.adicionar(_acesso(material_personalizado.id, aluno.id))

    with pytest.raises(IntegrityError):
        await repositorio.adicionar(_acesso(material_personalizado.id, aluno.id))
