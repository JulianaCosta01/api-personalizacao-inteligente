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


async def test_obter_retorna_bytes_do_objeto() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/storage/v1/object/materiais/materiais/x.pdf"
        return httpx.Response(200, content=b"%PDF-1.7 conteudo")

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")

    conteudo = await adaptador.obter("materiais/x.pdf")

    assert conteudo == b"%PDF-1.7 conteudo"


async def test_obter_com_objeto_inexistente_levanta_erro_de_storage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "not found"})

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.obter("materiais/inexistente.pdf")


async def test_obter_com_falha_do_servidor_levanta_erro_de_storage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.obter("materiais/x.pdf")


async def test_obter_nao_expoe_corpo_da_resposta_de_erro() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "segredo-interno-do-supabase"})

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")

    with pytest.raises(ErroDeStorage) as exc_info:
        await adaptador.obter("materiais/x.pdf")

    assert "segredo-interno-do-supabase" not in str(exc_info.value)


async def test_obter_rejeita_chave_com_path_traversal() -> None:
    adaptador = SupabaseStorageAdapter(_cliente(lambda r: httpx.Response(200)), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.obter("../etc/passwd")


async def test_salvar_rejeita_chave_com_barra_invertida() -> None:
    # Fase 7, Etapa 6 — Item 5: separador estilo Windows, usado tanto para
    # traversal ("..\\..\\etc\\passwd") quanto para caminhos absolutos
    # ("C:\\Windows\\System32").
    adaptador = SupabaseStorageAdapter(_cliente(lambda r: httpx.Response(200)), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.salvar("..\\..\\etc\\passwd", b"%PDF-1.7", TipoArquivo.PDF)


async def test_salvar_rejeita_chave_com_caminho_absoluto_windows() -> None:
    adaptador = SupabaseStorageAdapter(_cliente(lambda r: httpx.Response(200)), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.salvar("C:\\Windows\\System32\\config", b"%PDF-1.7", TipoArquivo.PDF)


async def test_salvar_rejeita_chave_com_byte_nulo() -> None:
    # Poison null byte: algumas APIs truncam a string no primeiro \x00,
    # permitindo contornar uma checagem de extensão feita antes deste ponto.
    adaptador = SupabaseStorageAdapter(_cliente(lambda r: httpx.Response(200)), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.salvar("materiais/x.pdf\x00.exe", b"%PDF-1.7", TipoArquivo.PDF)


async def test_remover_rejeita_chave_com_barra_invertida() -> None:
    adaptador = SupabaseStorageAdapter(_cliente(lambda r: httpx.Response(200)), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.remover("..\\..\\etc\\passwd")


async def test_remover_rejeita_chave_com_byte_nulo() -> None:
    adaptador = SupabaseStorageAdapter(_cliente(lambda r: httpx.Response(200)), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.remover("materiais/x.pdf\x00.exe")


async def test_obter_rejeita_chave_com_barra_invertida() -> None:
    adaptador = SupabaseStorageAdapter(_cliente(lambda r: httpx.Response(200)), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.obter("..\\..\\etc\\passwd")


async def test_obter_rejeita_chave_com_byte_nulo() -> None:
    adaptador = SupabaseStorageAdapter(_cliente(lambda r: httpx.Response(200)), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.obter("materiais/x.pdf\x00.exe")


async def test_criar_url_leitura_envia_metodo_caminho_e_expiracao_corretos() -> None:
    requisicoes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requisicoes.append(request)
        return httpx.Response(200, json={"signedURL": "/object/sign/materiais/x.pdf?token=abc123"})

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")
    await adaptador.criar_url_leitura("materiais/x.pdf", 300)

    assert len(requisicoes) == 1
    requisicao = requisicoes[0]
    assert requisicao.method == "POST"
    assert requisicao.url.path == "/storage/v1/object/sign/materiais/materiais/x.pdf"
    assert requisicao.headers["content-type"] == "application/json"
    assert requisicao.content == b'{"expiresIn":300}'


async def test_criar_url_leitura_monta_url_absoluta_sem_barra_duplicada() -> None:
    # A base_url do cliente HTTP sempre tem barra final (normalização do
    # próprio httpx); o path assinado devolvido pelo Supabase começa com "/" —
    # a concatenação não pode duplicar a barra entre os dois.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"signedURL": "/object/sign/materiais/x.pdf?token=abc123"})

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")
    url = await adaptador.criar_url_leitura("materiais/x.pdf", 300)

    assert url == "https://storage.teste/storage/v1/object/sign/materiais/x.pdf?token=abc123"
    assert "//object" not in url


async def test_criar_url_leitura_rejeita_chave_com_path_traversal() -> None:
    # Mesma validação de chave reaproveitada dos demais métodos — não duplica
    # todas as variantes já cobertas acima, só confirma que é chamada aqui também.
    adaptador = SupabaseStorageAdapter(_cliente(lambda r: httpx.Response(200)), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.criar_url_leitura("../etc/passwd", 300)


async def test_criar_url_leitura_com_falha_do_servidor_levanta_erro_de_storage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")

    with pytest.raises(ErroDeStorage):
        await adaptador.criar_url_leitura("materiais/x.pdf", 300)


async def test_criar_url_leitura_nao_expoe_corpo_da_resposta_de_erro() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "segredo-interno-do-supabase"})

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")

    with pytest.raises(ErroDeStorage) as exc_info:
        await adaptador.criar_url_leitura("materiais/x.pdf", 300)

    assert "segredo-interno-do-supabase" not in str(exc_info.value)


async def test_salvar_aceita_chave_uuid_normal_apos_reforco_de_validacao() -> None:
    # Regressão: o formato de chave gerado pelo próprio sistema continua
    # aceito integralmente após o reforço da validação.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Key": "materiais-personalizados/x.pdf"})

    adaptador = SupabaseStorageAdapter(_cliente(handler), bucket="materiais")

    await adaptador.salvar(
        "materiais-personalizados/3fa85f64-5717-4562-b3fc-2c963f66afa6.pdf",
        b"%PDF-1.7",
        TipoArquivo.PDF,
    )
