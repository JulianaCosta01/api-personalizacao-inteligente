from datetime import UTC, datetime
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao
from domain.perfil.perfil import Perfil
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from infrastructure.database.material.material_repository import MaterialRepositorySQLAlchemy
from infrastructure.database.perfil.perfil_repository import PerfilRepositorySQLAlchemy
from infrastructure.database.processamento.processamento_repository import (
    ProcessamentoRepositorySQLAlchemy,
)
from tests.api.conftest import SERVICE_TOKEN

_AUTH = {"Authorization": f"Bearer {SERVICE_TOKEN}"}


async def _criar_aluno(client: AsyncClient) -> str:
    resposta = await client.post(
        "/api/v1/alunos",
        json={
            "nome": "Kristiano Fernandes Plácido",
            "email": "kristiano@discente.ufma.br",
            "matricula": str(uuid4())[:20],
        },
        headers=_AUTH,
    )
    return str(resposta.json()["id"])


async def _criar_processamento(db_session: AsyncSession, aluno_id: str) -> Processamento:
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
        aluno_id=aluno_id,  # type: ignore[arg-type]
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
        aluno_id=aluno_id,  # type: ignore[arg-type]
        material_didatico_id=material.id,
        perfil_id=perfil.id,
        status=StatusProcessamento.PENDENTE,
        modelo_ia=None,
        data_criacao=datetime.now(UTC),
        inicio=None,
        fim=None,
        erro=None,
    )
    await ProcessamentoRepositorySQLAlchemy(db_session).adicionar(processamento)
    return processamento


async def test_post_logs_sem_processamento_retorna_201(client: AsyncClient) -> None:
    aluno_id = await _criar_aluno(client)

    response = await client.post(
        "/api/v1/logs",
        json={"aluno_id": aluno_id, "acao": "acesso_disciplina"},
        headers=_AUTH,
    )

    assert response.status_code == 201
    corpo = response.json()
    assert corpo["aluno_id"] == aluno_id
    assert corpo["processamento_id"] is None
    assert corpo["acao"] == "acesso_disciplina"
    assert corpo["timestamp"] is not None


async def test_post_logs_com_processamento_existente_retorna_201(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    aluno_id = await _criar_aluno(client)
    processamento = await _criar_processamento(db_session, aluno_id)

    response = await client.post(
        "/api/v1/logs",
        json={
            "aluno_id": aluno_id,
            "processamento_id": str(processamento.id),
            "acao": "download_material_personalizado",
            "descricao": "Download concluído.",
        },
        headers=_AUTH,
    )

    assert response.status_code == 201
    corpo = response.json()
    assert corpo["processamento_id"] == str(processamento.id)
    assert corpo["descricao"] == "Download concluído."


async def test_post_logs_com_aluno_inexistente_retorna_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/logs",
        json={"aluno_id": str(uuid4()), "acao": "acesso_disciplina"},
        headers=_AUTH,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ALUNO_NAO_ENCONTRADO"


async def test_post_logs_com_processamento_inexistente_retorna_404(client: AsyncClient) -> None:
    aluno_id = await _criar_aluno(client)

    response = await client.post(
        "/api/v1/logs",
        json={
            "aluno_id": aluno_id,
            "processamento_id": str(uuid4()),
            "acao": "erro_personalizacao",
        },
        headers=_AUTH,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROCESSAMENTO_NAO_ENCONTRADO"


async def test_post_logs_com_aluno_dono_do_processamento_retorna_201(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    aluno_id = await _criar_aluno(client)
    processamento = await _criar_processamento(db_session, aluno_id)

    response = await client.post(
        "/api/v1/logs",
        json={
            "aluno_id": aluno_id,
            "processamento_id": str(processamento.id),
            "acao": "download_material_personalizado",
        },
        headers=_AUTH,
    )

    assert response.status_code == 201
    assert response.json()["aluno_id"] == aluno_id


async def test_post_logs_com_aluno_diferente_do_dono_do_processamento_retorna_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # aluno_id e processamento_id (corpo) precisam apontar para a mesma pessoa,
    # mesma proteção BOLA/IDOR já existente em PUT /materiais-personalizados/{id}/acesso.
    dono_id = await _criar_aluno(client)
    outro_aluno_id = await _criar_aluno(client)
    processamento = await _criar_processamento(db_session, dono_id)

    response = await client.post(
        "/api/v1/logs",
        json={
            "aluno_id": outro_aluno_id,
            "processamento_id": str(processamento.id),
            "acao": "download_material_personalizado",
        },
        headers=_AUTH,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ALUNO_ID_INVALIDO"

    # Não cria registro parcial: a listagem do processamento continua vazia.
    listagem = await client.get(f"/api/v1/processamentos/{processamento.id}/logs", headers=_AUTH)
    assert listagem.json()["pagination"]["total_items"] == 0


async def test_post_logs_sem_campo_obrigatorio_retorna_400(client: AsyncClient) -> None:
    aluno_id = await _criar_aluno(client)

    response = await client.post(
        "/api/v1/logs",
        json={"aluno_id": aluno_id},
        headers=_AUTH,
    )

    assert response.status_code == 400


async def test_post_logs_sem_token_retorna_401(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/logs", json={"aluno_id": str(uuid4()), "acao": "acesso_disciplina"}
    )

    assert response.status_code == 401


async def test_get_logs_do_processamento_retorna_200_ordenado(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    aluno_id = await _criar_aluno(client)
    processamento = await _criar_processamento(db_session, aluno_id)
    for acao in ("inicio_processamento", "fim_processamento"):
        await client.post(
            "/api/v1/logs",
            json={
                "aluno_id": aluno_id,
                "processamento_id": str(processamento.id),
                "acao": acao,
            },
            headers=_AUTH,
        )

    response = await client.get(f"/api/v1/processamentos/{processamento.id}/logs", headers=_AUTH)

    assert response.status_code == 200
    corpo = response.json()
    assert corpo["pagination"]["total_items"] == 2
    assert len(corpo["data"]) == 2
    assert corpo["data"][0]["timestamp"] <= corpo["data"][1]["timestamp"]


async def test_get_logs_do_processamento_inexistente_retorna_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/processamentos/{uuid4()}/logs", headers=_AUTH)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROCESSAMENTO_NAO_ENCONTRADO"


async def test_get_logs_do_processamento_sem_logs_retorna_lista_vazia(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    aluno_id = await _criar_aluno(client)
    processamento = await _criar_processamento(db_session, aluno_id)

    response = await client.get(f"/api/v1/processamentos/{processamento.id}/logs", headers=_AUTH)

    assert response.status_code == 200
    corpo = response.json()
    assert corpo["data"] == []
    assert corpo["pagination"]["total_items"] == 0
