from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio
from httpx import AsyncClient
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
from infrastructure.database.perfil.perfil_repository import PerfilRepositorySQLAlchemy
from infrastructure.database.processamento.processamento_repository import (
    ProcessamentoRepositorySQLAlchemy,
)
from presentation.api.main import app
from presentation.api.routers.material_personalizado import _storage_material_personalizado
from tests.api.conftest import SERVICE_TOKEN
from tests.unit.application.material.fakes import ObjectStorageFake

_AUTH = {"Authorization": f"Bearer {SERVICE_TOKEN}"}


@pytest_asyncio.fixture(autouse=True)
async def storage_fake() -> AsyncGenerator[ObjectStorageFake]:
    # Substitui o Supabase Storage real por um dublê em memória. autouse=True porque o
    # FastAPI resolve o Depends() antes do handler, mesmo em 404/409.
    fake = ObjectStorageFake()
    app.dependency_overrides[_storage_material_personalizado] = lambda: fake
    yield fake
    app.dependency_overrides.pop(_storage_material_personalizado, None)


async def _criar_processamento(
    db_session: AsyncSession, status: StatusProcessamento
) -> Processamento:
    # Semeado direto via repositório: um Processamento concluído só existe, em
    # uso normal, depois do pipeline real do Worker: inalcançável pela API sozinha aqui.
    aluno = Aluno(
        id=uuid4(),
        nome="Kristiano Fernandes Plácido",
        email=f"{uuid4()}@discente.ufma.br",
        matricula=str(uuid4())[:20],
        grupo_experimental=GrupoExperimental.EXPERIMENTAL,
        data_cadastro=datetime.now(UTC),
    )
    await AlunoRepositorySQLAlchemy(db_session).adicionar(aluno)

    material = MaterialDidatico(
        id=uuid4(),
        titulo="Introdução a Grafos",
        nome_arquivo=f"{uuid4()}.pdf",
        tipo_arquivo=TipoArquivo.PDF,
        caminho_storage=f"materiais/{uuid4()}.pdf",
        versao=1,
        data_upload=datetime.now(UTC),
    )
    await MaterialRepositorySQLAlchemy(db_session).adicionar(material)

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
    await PerfilRepositorySQLAlchemy(db_session).adicionar(perfil)

    processamento = Processamento(
        id=uuid4(),
        aluno_id=aluno.id,
        material_didatico_id=material.id,
        perfil_id=perfil.id,
        status=status,
        modelo_ia="gemini-3.1-flash-lite" if status != StatusProcessamento.PENDENTE else None,
        data_criacao=datetime.now(UTC),
        inicio=datetime.now(UTC) if status != StatusProcessamento.PENDENTE else None,
        fim=datetime.now(UTC) if status == StatusProcessamento.CONCLUIDO else None,
        erro=None,
    )
    await ProcessamentoRepositorySQLAlchemy(db_session).adicionar(processamento)
    return processamento


async def _criar_material_personalizado(
    db_session: AsyncSession,
    processamento_id: object,
    storage_fake: ObjectStorageFake | None = None,
) -> MaterialPersonalizado:
    material_personalizado = MaterialPersonalizado(
        id=uuid4(),
        processamento_id=processamento_id,  # type: ignore[arg-type]
        titulo="Introdução a Grafos (Personalizado)",
        caminho_pdf=f"materiais-personalizados/{uuid4()}.pdf",
        resumo="Resumo do material adaptado ao estilo do aluno.",
        data_geracao=datetime.now(UTC),
    )
    await MaterialPersonalizadoRepositorySQLAlchemy(db_session).adicionar(material_personalizado)
    if storage_fake is not None:
        # O PDF em si não é gravado aqui (só a linha do banco): o fake precisa "conhecer"
        # a chave para assinar a URL, como o adaptador real exigiria com o objeto no bucket.
        storage_fake.salvos[material_personalizado.caminho_pdf] = b"conteudo fake"
    return material_personalizado


async def test_get_material_do_processamento_concluido_retorna_200_com_url_assinada(
    client: AsyncClient, db_session: AsyncSession, storage_fake: ObjectStorageFake
) -> None:
    processamento = await _criar_processamento(db_session, StatusProcessamento.CONCLUIDO)
    material_personalizado = await _criar_material_personalizado(
        db_session, processamento.id, storage_fake
    )

    response = await client.get(
        f"/api/v1/processamentos/{processamento.id}/material", headers=_AUTH
    )

    assert response.status_code == 200
    corpo = response.json()
    assert corpo["id"] == str(material_personalizado.id)
    assert corpo["processamento_id"] == str(processamento.id)
    # Nunca a chave bruta do Storage: sempre uma URL assinada.
    assert corpo["caminho_pdf"] != material_personalizado.caminho_pdf
    assert corpo["caminho_pdf"].startswith("http")


async def test_get_material_do_processamento_pendente_retorna_409(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    processamento = await _criar_processamento(db_session, StatusProcessamento.PENDENTE)

    response = await client.get(
        f"/api/v1/processamentos/{processamento.id}/material", headers=_AUTH
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MATERIAL_PERSONALIZADO_INDISPONIVEL"


async def test_get_material_do_processamento_inexistente_retorna_404(
    client: AsyncClient,
) -> None:
    response = await client.get(f"/api/v1/processamentos/{uuid4()}/material", headers=_AUTH)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROCESSAMENTO_NAO_ENCONTRADO"


async def test_get_material_sem_token_retorna_401(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/processamentos/{uuid4()}/material")

    assert response.status_code == 401


async def test_get_material_personalizado_por_id_retorna_200(
    client: AsyncClient, db_session: AsyncSession, storage_fake: ObjectStorageFake
) -> None:
    processamento = await _criar_processamento(db_session, StatusProcessamento.CONCLUIDO)
    material_personalizado = await _criar_material_personalizado(
        db_session, processamento.id, storage_fake
    )

    response = await client.get(
        f"/api/v1/materiais-personalizados/{material_personalizado.id}", headers=_AUTH
    )

    assert response.status_code == 200
    corpo = response.json()
    assert corpo["id"] == str(material_personalizado.id)
    assert corpo["titulo"] == material_personalizado.titulo


async def test_get_material_personalizado_por_id_inexistente_retorna_404(
    client: AsyncClient,
) -> None:
    response = await client.get(f"/api/v1/materiais-personalizados/{uuid4()}", headers=_AUTH)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MATERIAL_PERSONALIZADO_NAO_ENCONTRADO"
