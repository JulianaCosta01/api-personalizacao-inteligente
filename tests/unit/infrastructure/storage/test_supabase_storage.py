from collections.abc import Callable

import httpx
import pytest

from domain.material.tipo_arquivo import TipoArquivo
from infrastructure.storage.supabase_storage import ErroDeStorage, SupabaseStorageAdapter


def _cliente(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://storage.teste/storage/v1", transport=httpx.MockTransport(handler)
    )


async def test_salvar_envia_metodo_caminho_e_content_type_corretos() -> None:
    requisicoes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requisicoes.append(request)
        return httpx.Response(200, json={"Key": "materiais/x.pdf"})

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")
    await adaptador.salvar("materiais/x.pdf", b"%PDF-1.7", TipoArquivo.PDF)

    assert len(requisicoes) == 1
    requisicao = requisicoes[0]
    assert requisicao.method == "POST"
    assert requisicao.url.path == "/storage/v1/object/materiais/materiais/x.pdf"
    assert requisicao.headers["content-type"] == "application/pdf"
    assert requisicao.content == b"%PDF-1.7"


async def test_salvar_com_erro_de_autenticacao_levanta_erro_de_storage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid token"})

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.salvar("materiais/x.pdf", b"%PDF-1.7", TipoArquivo.PDF)


async def test_salvar_com_falha_do_servidor_levanta_erro_de_storage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.salvar("materiais/x.pdf", b"%PDF-1.7", TipoArquivo.PDF)


async def test_erro_de_storage_nao_expoe_corpo_da_resposta() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "segredo-interno-do-supabase"})

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")

    with pytest.raises(ErroDeStorage) as exc_info:
        await adaptador.salvar("materiais/x.pdf", b"%PDF-1.7", TipoArquivo.PDF)

    assert "segredo-interno-do-supabase" not in str(exc_info.value)


async def test_remover_bem_sucedido_nao_levanta_erro() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return httpx.Response(200, json={"message": "Successfully deleted"})

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")

    await adaptador.remover("materiais/x.pdf")


async def test_remover_com_falha_levanta_erro_de_storage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "not found"})

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.remover("materiais/x.pdf")


async def test_salvar_rejeita_chave_com_path_traversal() -> None:
    adaptador = SupabaseStorageAdapter(_cliente(lambda r: httpx.Response(200)), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.salvar("../etc/passwd", b"%PDF-1.7", TipoArquivo.PDF)


async def test_remover_rejeita_chave_absoluta() -> None:
    adaptador = SupabaseStorageAdapter(_cliente(lambda r: httpx.Response(200)), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.remover("/etc/passwd")
