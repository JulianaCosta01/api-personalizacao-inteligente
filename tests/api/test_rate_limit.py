from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest_asyncio
from httpx import AsyncClient, Response

from presentation.api.main import app
from presentation.api.rate_limit import (
    LimitadorDeTaxa,
    _limitador_materiais,
    _limitador_processamentos,
)
from presentation.api.routers.material import _storage_material
from presentation.api.routers.perfil import _llm
from presentation.api.routers.processamento import _fila
from tests.api.conftest import SERVICE_TOKEN
from tests.unit.application.material.fakes import ObjectStorageFake
from tests.unit.application.perfil.fakes import LLMFake
from tests.unit.application.processamento.fakes import QueueFake

_AUTH = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
_PDF_VALIDO = b"%PDF-1.7\nconteudo qualquer"


class _RelogioFalso:
    def __init__(self, inicio: float = 0.0) -> None:
        self.agora = inicio

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


@pytest_asyncio.fixture(autouse=True)
async def dependencias_externas_fake() -> AsyncGenerator[None]:
    # Mesmas dependências externas dubladas em test_processamento_router.py —
    # o cenário deste arquivo também passa pelo fluxo real de criação de
    # Aluno/Material/Perfil/Processamento antes de exercitar o rate limit.
    app.dependency_overrides[_storage_material] = lambda: ObjectStorageFake()
    app.dependency_overrides[_llm] = lambda: LLMFake()
    app.dependency_overrides[_fila] = lambda: QueueFake()
    yield
    app.dependency_overrides.pop(_storage_material, None)
    app.dependency_overrides.pop(_llm, None)
    app.dependency_overrides.pop(_fila, None)


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


async def _criar_material(client: AsyncClient) -> str:
    resposta = await client.post(
        "/api/v1/materiais",
        data={"titulo": "Introdução a Grafos"},
        files={"arquivo": ("grafos.pdf", _PDF_VALIDO, "application/pdf")},
        headers=_AUTH,
    )
    return str(resposta.json()["id"])


async def _criar_perfil(client: AsyncClient, aluno_id: str) -> str:
    resposta = await client.post(
        f"/api/v1/alunos/{aluno_id}/perfil",
        json={
            "estilo_processamento": "Ativo",
            "percepcao": "Sensorial",
            "entrada": "Visual",
            "compreensao": "Sequencial",
        },
        headers=_AUTH,
    )
    return str(resposta.json()["id"])


async def _cenario_completo(client: AsyncClient) -> tuple[str, str]:
    aluno_id = await _criar_aluno(client)
    material_id = await _criar_material(client)
    await _criar_perfil(client, aluno_id)
    return aluno_id, material_id


async def _post_processamento(client: AsyncClient, aluno_id: str, material_id: str) -> Response:
    return await client.post(
        "/api/v1/processamentos",
        json={"aluno_id": aluno_id, "material_didatico_id": material_id},
        headers=_AUTH,
    )


def _sobrescrever_limitador_processamentos(limite: int, relogio: _RelogioFalso) -> None:
    # A instância precisa ser criada UMA vez fora do lambda: o FastAPI chama a
    # dependency override a cada requisição, então um lambda que construísse
    # um LimitadorDeTaxa novo por chamada nunca acumularia contagem alguma
    # entre requisições dentro do mesmo teste.
    limitador = LimitadorDeTaxa(limite=limite, janela_segundos=60.0, relogio=relogio)
    app.dependency_overrides[_limitador_processamentos] = lambda: limitador


def _sobrescrever_limitador_materiais(limite: int, relogio: _RelogioFalso) -> None:
    limitador = LimitadorDeTaxa(limite=limite, janela_segundos=60.0, relogio=relogio)
    app.dependency_overrides[_limitador_materiais] = lambda: limitador


async def test_post_processamentos_dentro_do_limite_continua_funcionando(
    client: AsyncClient,
) -> None:
    _sobrescrever_limitador_processamentos(limite=2, relogio=_RelogioFalso())
    aluno_id, material_id = await _cenario_completo(client)

    resposta_1 = await _post_processamento(client, aluno_id, material_id)
    resposta_2 = await _post_processamento(client, aluno_id, material_id)

    assert resposta_1.status_code == 202
    assert resposta_2.status_code == 202


async def test_post_processamentos_excede_limite_retorna_429_com_envelope_padrao(
    client: AsyncClient,
) -> None:
    _sobrescrever_limitador_processamentos(limite=1, relogio=_RelogioFalso())
    aluno_id, material_id = await _cenario_completo(client)

    resposta_1 = await _post_processamento(client, aluno_id, material_id)
    resposta_2 = await _post_processamento(client, aluno_id, material_id)

    assert resposta_1.status_code == 202
    assert resposta_2.status_code == 429
    assert resposta_2.json() == {
        "error": {
            "code": "LIMITE_DE_REQUISICOES_EXCEDIDO",
            "message": "Limite de requisições excedido. Tente novamente em instantes.",
            "details": {},
        }
    }


async def test_post_processamentos_janela_expira_e_libera_novas_requisicoes(
    client: AsyncClient,
) -> None:
    relogio = _RelogioFalso()
    _sobrescrever_limitador_processamentos(limite=1, relogio=relogio)
    aluno_id, material_id = await _cenario_completo(client)

    resposta_1 = await _post_processamento(client, aluno_id, material_id)
    resposta_2 = await _post_processamento(client, aluno_id, material_id)
    relogio.avancar(60.0)
    resposta_3 = await _post_processamento(client, aluno_id, material_id)

    assert resposta_1.status_code == 202
    assert resposta_2.status_code == 429
    assert resposta_3.status_code == 202


async def test_post_processamentos_bloqueado_nao_chega_a_criar_registro(
    client: AsyncClient,
) -> None:
    # O 429 precisa interromper a requisição antes de qualquer efeito
    # colateral (nenhum Processamento novo persistido) — não é só o código
    # HTTP que importa, é também não ter processado nada além da checagem.
    _sobrescrever_limitador_processamentos(limite=1, relogio=_RelogioFalso())
    aluno_id, material_id = await _cenario_completo(client)
    await _post_processamento(client, aluno_id, material_id)

    resposta_bloqueada = await _post_processamento(client, aluno_id, material_id)

    assert resposta_bloqueada.status_code == 429
    listagem = await client.get(f"/api/v1/alunos/{aluno_id}/processamentos", headers=_AUTH)
    assert listagem.json()["pagination"]["total_items"] == 1


async def test_post_materiais_dentro_do_limite_continua_funcionando(
    client: AsyncClient,
) -> None:
    _sobrescrever_limitador_materiais(limite=2, relogio=_RelogioFalso())

    resposta_1 = await client.post(
        "/api/v1/materiais",
        data={"titulo": "Material A"},
        files={"arquivo": ("a.pdf", _PDF_VALIDO, "application/pdf")},
        headers=_AUTH,
    )
    resposta_2 = await client.post(
        "/api/v1/materiais",
        data={"titulo": "Material B"},
        files={"arquivo": ("b.pdf", _PDF_VALIDO, "application/pdf")},
        headers=_AUTH,
    )

    assert resposta_1.status_code == 201
    assert resposta_2.status_code == 201


async def test_post_materiais_excede_limite_retorna_429_com_envelope_padrao(
    client: AsyncClient,
) -> None:
    _sobrescrever_limitador_materiais(limite=1, relogio=_RelogioFalso())

    resposta_1 = await client.post(
        "/api/v1/materiais",
        data={"titulo": "Material A"},
        files={"arquivo": ("a.pdf", _PDF_VALIDO, "application/pdf")},
        headers=_AUTH,
    )
    resposta_2 = await client.post(
        "/api/v1/materiais",
        data={"titulo": "Material B"},
        files={"arquivo": ("b.pdf", _PDF_VALIDO, "application/pdf")},
        headers=_AUTH,
    )

    assert resposta_1.status_code == 201
    assert resposta_2.status_code == 429
    assert resposta_2.json()["error"]["code"] == "LIMITE_DE_REQUISICOES_EXCEDIDO"


async def test_rate_limit_nao_se_aplica_a_endpoints_de_leitura(client: AsyncClient) -> None:
    # Confirma que o Depends foi colocado só na rota POST /materiais — GET
    # continua liberado mesmo com o limitador de materiais zerado.
    _sobrescrever_limitador_materiais(limite=0, relogio=_RelogioFalso())

    resposta = await client.get("/api/v1/materiais", headers=_AUTH)

    assert resposta.status_code == 200


async def test_post_processamentos_sem_token_retorna_401_sem_consumir_limite(
    client: AsyncClient,
) -> None:
    # validar_token_servico roda antes do limitador (Depends dentro de
    # limitar_processamentos) — uma requisição sem token nunca chega a
    # incrementar o contador.
    relogio = _RelogioFalso()
    _sobrescrever_limitador_processamentos(limite=1, relogio=relogio)
    aluno_id, material_id = await _cenario_completo(client)

    sem_token = await client.post(
        "/api/v1/processamentos",
        json={"aluno_id": aluno_id, "material_didatico_id": material_id},
    )
    com_token = await _post_processamento(client, aluno_id, material_id)

    assert sem_token.status_code == 401
    assert com_token.status_code == 202
