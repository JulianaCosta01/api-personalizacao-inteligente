from datetime import UTC, datetime
from uuid import uuid4

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
from tests.api.conftest import SERVICE_TOKEN

_AUTH = {"Authorization": f"Bearer {SERVICE_TOKEN}"}


async def _criar_material_personalizado(
    db_session: AsyncSession,
) -> tuple[Aluno, MaterialPersonalizado]:
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
        status=StatusProcessamento.CONCLUIDO,
        modelo_ia="gemini-3.1-flash-lite",
        data_criacao=datetime.now(UTC),
        inicio=datetime.now(UTC),
        fim=datetime.now(UTC),
        erro=None,
    )
    await ProcessamentoRepositorySQLAlchemy(db_session).adicionar(processamento)

    material_personalizado = MaterialPersonalizado(
        id=uuid4(),
        processamento_id=processamento.id,
        titulo="Introdução a Grafos (Personalizado)",
        caminho_pdf=f"materiais-personalizados/{uuid4()}.pdf",
        resumo="Resumo do material adaptado ao estilo do aluno.",
        data_geracao=datetime.now(UTC),
    )
    await MaterialPersonalizadoRepositorySQLAlchemy(db_session).adicionar(material_personalizado)

    return aluno, material_personalizado


async def test_put_acesso_primeira_chamada_retorna_201(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    aluno, material_personalizado = await _criar_material_personalizado(db_session)

    response = await client.put(
        f"/api/v1/materiais-personalizados/{material_personalizado.id}/acesso",
        json={
            "aluno_id": str(aluno.id),
            "tempo_leitura_incremento_segundos": 60,
            "porcentagem_leitura": 0.2,
            "download_realizado": False,
        },
        headers=_AUTH,
    )

    assert response.status_code == 201
    corpo = response.json()
    assert corpo["aluno_id"] == str(aluno.id)
    assert corpo["quantidade_acessos"] == 1
    assert corpo["tempo_total_leitura"] == 60
    assert corpo["status_leitura"] == "EM_ANDAMENTO"


async def test_put_acesso_segunda_chamada_retorna_200_e_acumula(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    aluno, material_personalizado = await _criar_material_personalizado(db_session)
    corpo_requisicao = {
        "aluno_id": str(aluno.id),
        "tempo_leitura_incremento_segundos": 60,
        "porcentagem_leitura": 0.2,
        "download_realizado": False,
    }
    await client.put(
        f"/api/v1/materiais-personalizados/{material_personalizado.id}/acesso",
        json=corpo_requisicao,
        headers=_AUTH,
    )

    response = await client.put(
        f"/api/v1/materiais-personalizados/{material_personalizado.id}/acesso",
        json={
            "aluno_id": str(aluno.id),
            "tempo_leitura_incremento_segundos": 120,
            "porcentagem_leitura": 1.0,
            "download_realizado": True,
        },
        headers=_AUTH,
    )

    assert response.status_code == 200
    corpo = response.json()
    assert corpo["quantidade_acessos"] == 2
    assert corpo["tempo_total_leitura"] == 180
    assert corpo["download_realizado"] is True
    assert corpo["status_leitura"] == "CONCLUIDO"


async def test_put_acesso_com_aluno_diferente_do_dono_retorna_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, material_personalizado = await _criar_material_personalizado(db_session)

    response = await client.put(
        f"/api/v1/materiais-personalizados/{material_personalizado.id}/acesso",
        json={
            "aluno_id": str(uuid4()),
            "tempo_leitura_incremento_segundos": 10,
            "porcentagem_leitura": 0.1,
            "download_realizado": False,
        },
        headers=_AUTH,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ALUNO_ID_INVALIDO"


async def test_put_acesso_de_um_aluno_real_em_material_de_outro_aluno_retorna_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Cenário de BOLA/IDOR propriamente dito: não um aluno_id qualquer/
    # inexistente, mas um segundo Aluno de verdade, cadastrado no sistema,
    # tentando registrar acesso com a própria identidade num Material
    # Personalizado que pertence a outro Aluno (via processamento.aluno_id).
    # O SERVICE_TOKEN por si só não distingue quem está fazendo a chamada
    # (feedback_bola_idor_authorization) — a checagem de posse é o que
    # impede isso.
    _, material_personalizado = await _criar_material_personalizado(db_session)
    aluno_intruso = Aluno(
        id=uuid4(),
        nome="Outro Aluno",
        email=f"{uuid4()}@discente.ufma.br",
        matricula=str(uuid4())[:20],
        grupo_experimental=GrupoExperimental.CONTROLE,
        data_cadastro=datetime.now(UTC),
    )
    await AlunoRepositorySQLAlchemy(db_session).adicionar(aluno_intruso)

    response = await client.put(
        f"/api/v1/materiais-personalizados/{material_personalizado.id}/acesso",
        json={
            "aluno_id": str(aluno_intruso.id),
            "tempo_leitura_incremento_segundos": 10,
            "porcentagem_leitura": 0.1,
            "download_realizado": False,
        },
        headers=_AUTH,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ALUNO_ID_INVALIDO"


async def test_put_acesso_material_personalizado_inexistente_retorna_404(
    client: AsyncClient,
) -> None:
    response = await client.put(
        f"/api/v1/materiais-personalizados/{uuid4()}/acesso",
        json={
            "aluno_id": str(uuid4()),
            "tempo_leitura_incremento_segundos": 10,
            "porcentagem_leitura": 0.1,
            "download_realizado": False,
        },
        headers=_AUTH,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MATERIAL_PERSONALIZADO_NAO_ENCONTRADO"


async def test_put_acesso_sem_token_retorna_401(client: AsyncClient) -> None:
    response = await client.put(
        f"/api/v1/materiais-personalizados/{uuid4()}/acesso",
        json={
            "aluno_id": str(uuid4()),
            "tempo_leitura_incremento_segundos": 10,
            "porcentagem_leitura": 0.1,
            "download_realizado": False,
        },
    )

    assert response.status_code == 401


async def test_get_acesso_apos_put_retorna_200(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    aluno, material_personalizado = await _criar_material_personalizado(db_session)
    await client.put(
        f"/api/v1/materiais-personalizados/{material_personalizado.id}/acesso",
        json={
            "aluno_id": str(aluno.id),
            "tempo_leitura_incremento_segundos": 30,
            "porcentagem_leitura": 0.1,
            "download_realizado": False,
        },
        headers=_AUTH,
    )

    response = await client.get(
        f"/api/v1/materiais-personalizados/{material_personalizado.id}/acesso", headers=_AUTH
    )

    assert response.status_code == 200
    corpo = response.json()
    assert corpo["aluno_id"] == str(aluno.id)
    assert corpo["quantidade_acessos"] == 1


async def test_get_acesso_sem_acesso_previo_retorna_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, material_personalizado = await _criar_material_personalizado(db_session)

    response = await client.get(
        f"/api/v1/materiais-personalizados/{material_personalizado.id}/acesso", headers=_AUTH
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACESSO_NAO_ENCONTRADO"


async def test_get_acesso_sem_token_retorna_401(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/materiais-personalizados/{uuid4()}/acesso")

    assert response.status_code == 401


async def test_put_acesso_porcentagem_leitura_aceita_limites_e_fracao_intermediaria(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Documento 3 §4.7: porcentagem_leitura é uma fração entre 0 e 1
    # (ex.: 0.78 = 78%). 0, 1 e um valor intermediário devem ser aceitos.
    aluno, material_personalizado = await _criar_material_personalizado(db_session)

    for porcentagem_leitura in (0.0, 0.78, 1.0):
        response = await client.put(
            f"/api/v1/materiais-personalizados/{material_personalizado.id}/acesso",
            json={
                "aluno_id": str(aluno.id),
                "tempo_leitura_incremento_segundos": 10,
                "porcentagem_leitura": porcentagem_leitura,
                "download_realizado": False,
            },
            headers=_AUTH,
        )

        assert response.status_code in (200, 201)
        assert response.json()["porcentagem_leitura"] == porcentagem_leitura


async def test_put_acesso_com_porcentagem_leitura_maior_que_1_retorna_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # Regressão do bug real encontrado na validação E2E: um cliente que envie
    # um percentual "cru" (25.0) precisa receber um 400 claro do Pydantic,
    # não um 500 vindo de overflow do Numeric(5, 4) no Postgres.
    aluno, material_personalizado = await _criar_material_personalizado(db_session)

    response = await client.put(
        f"/api/v1/materiais-personalizados/{material_personalizado.id}/acesso",
        json={
            "aluno_id": str(aluno.id),
            "tempo_leitura_incremento_segundos": 10,
            "porcentagem_leitura": 25.0,
            "download_realizado": False,
        },
        headers=_AUTH,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUISICAO_INVALIDA"


async def test_put_acesso_com_porcentagem_leitura_negativa_retorna_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    aluno, material_personalizado = await _criar_material_personalizado(db_session)

    response = await client.put(
        f"/api/v1/materiais-personalizados/{material_personalizado.id}/acesso",
        json={
            "aluno_id": str(aluno.id),
            "tempo_leitura_incremento_segundos": 10,
            "porcentagem_leitura": -0.1,
            "download_realizado": False,
        },
        headers=_AUTH,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUISICAO_INVALIDA"
