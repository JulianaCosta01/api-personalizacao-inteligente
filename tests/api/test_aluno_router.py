from uuid import uuid4

from httpx import AsyncClient

from tests.api.conftest import SERVICE_TOKEN

_AUTH = {"Authorization": f"Bearer {SERVICE_TOKEN}"}


def _payload_cadastro(matricula: str | None = None) -> dict[str, str]:
    return {
        "nome": "Kristiano Fernandes Plácido",
        "email": "kristiano@discente.ufma.br",
        "matricula": matricula or str(uuid4())[:20],
    }


async def test_post_autenticado_cria_aluno_e_retorna_201(client: AsyncClient) -> None:
    response = await client.post("/api/v1/alunos", json=_payload_cadastro(), headers=_AUTH)

    assert response.status_code == 201
    corpo = response.json()
    assert corpo["grupo_experimental"] in ("experimental", "controle")
    assert "id" in corpo


async def test_post_sem_token_retorna_401(client: AsyncClient) -> None:
    response = await client.post("/api/v1/alunos", json=_payload_cadastro())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_AUSENTE"


async def test_post_repetido_com_mesma_matricula_retorna_200_e_mesmo_id(
    client: AsyncClient,
) -> None:
    payload = _payload_cadastro()

    primeiro = await client.post("/api/v1/alunos", json=payload, headers=_AUTH)
    segundo = await client.post("/api/v1/alunos", json=payload, headers=_AUTH)

    assert primeiro.status_code == 201
    assert segundo.status_code == 200
    assert segundo.json()["id"] == primeiro.json()["id"]


async def test_post_com_campo_desconhecido_retorna_400(client: AsyncClient) -> None:
    payload = _payload_cadastro()
    payload["campo_nao_permitido"] = "valor-qualquer"

    response = await client.post("/api/v1/alunos", json=payload, headers=_AUTH)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUISICAO_INVALIDA"


async def test_post_com_email_invalido_retorna_400(client: AsyncClient) -> None:
    payload = _payload_cadastro()
    payload["email"] = "nao-e-um-email"

    response = await client.post("/api/v1/alunos", json=payload, headers=_AUTH)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUISICAO_INVALIDA"


async def test_persistencia_real_entre_requisicoes_http_separadas(client: AsyncClient) -> None:
    # Regressão do bug de sessão sem commit: só passa se o GET enxergar o que
    # o POST anterior gravou de fato no banco, cada um em sua própria requisição.
    cadastro = await client.post("/api/v1/alunos", json=_payload_cadastro(), headers=_AUTH)
    aluno_id = cadastro.json()["id"]

    consulta = await client.get(f"/api/v1/alunos/{aluno_id}", headers=_AUTH)

    assert consulta.status_code == 200
    assert consulta.json()["id"] == aluno_id


async def test_get_autenticado_retorna_aluno_cadastrado(client: AsyncClient) -> None:
    cadastro = await client.post("/api/v1/alunos", json=_payload_cadastro(), headers=_AUTH)
    aluno_id = cadastro.json()["id"]

    response = await client.get(f"/api/v1/alunos/{aluno_id}", headers=_AUTH)

    assert response.status_code == 200
    assert response.json()["nome"] == "Kristiano Fernandes Plácido"


async def test_get_sem_token_retorna_401(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/alunos/{uuid4()}")

    assert response.status_code == 401


async def test_get_aluno_inexistente_retorna_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/alunos/{uuid4()}", headers=_AUTH)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ALUNO_NAO_ENCONTRADO"


async def test_get_com_uuid_invalido_no_path_retorna_400(client: AsyncClient) -> None:
    response = await client.get("/api/v1/alunos/nao-e-um-uuid", headers=_AUTH)

    assert response.status_code == 400


async def test_put_autenticado_atualiza_somente_nome_e_email(client: AsyncClient) -> None:
    cadastro = await client.post("/api/v1/alunos", json=_payload_cadastro(), headers=_AUTH)
    aluno_id = cadastro.json()["id"]

    response = await client.put(
        f"/api/v1/alunos/{aluno_id}",
        json={"nome": "Novo Nome", "email": "novo@discente.ufma.br"},
        headers=_AUTH,
    )

    assert response.status_code == 200
    corpo = response.json()
    assert corpo["nome"] == "Novo Nome"
    assert corpo["email"] == "novo@discente.ufma.br"
    assert corpo["matricula"] == cadastro.json()["matricula"]
    assert corpo["grupo_experimental"] == cadastro.json()["grupo_experimental"]


async def test_put_sem_token_retorna_401(client: AsyncClient) -> None:
    response = await client.put(f"/api/v1/alunos/{uuid4()}", json={"nome": "X", "email": "x@x.com"})

    assert response.status_code == 401


async def test_put_com_campo_proibido_retorna_400(client: AsyncClient) -> None:
    cadastro = await client.post("/api/v1/alunos", json=_payload_cadastro(), headers=_AUTH)
    aluno_id = cadastro.json()["id"]

    response = await client.put(
        f"/api/v1/alunos/{aluno_id}",
        json={"nome": "Novo Nome", "email": "novo@discente.ufma.br", "matricula": "outra"},
        headers=_AUTH,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "REQUISICAO_INVALIDA"


async def test_put_aluno_inexistente_retorna_404(client: AsyncClient) -> None:
    response = await client.put(
        f"/api/v1/alunos/{uuid4()}",
        json={"nome": "X", "email": "x@discente.ufma.br"},
        headers=_AUTH,
    )

    assert response.status_code == 404


async def test_erro_de_token_invalido_nao_vaza_o_token_configurado(client: AsyncClient) -> None:
    response = await client.get(
        f"/api/v1/alunos/{uuid4()}", headers={"Authorization": "Bearer token-errado"}
    )

    assert response.status_code == 401
    assert SERVICE_TOKEN not in response.text
