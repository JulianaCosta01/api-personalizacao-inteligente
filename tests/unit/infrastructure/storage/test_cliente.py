from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from infrastructure.storage.cliente import get_storage_client


@pytest.fixture
def cliente() -> Iterator[httpx.AsyncClient]:
    # get_storage_client usa lru_cache: sem limpar, o cliente criado aqui vazaria para outros
    # testes (e um cliente de outro teste mascararia a configuração verificada).
    get_storage_client.cache_clear()
    with patch(
        "infrastructure.storage.cliente.get_settings",
        return_value=SimpleNamespace(
            storage_url="https://storage.teste", storage_service_key="chave-de-teste"
        ),
    ):
        yield get_storage_client()
    get_storage_client.cache_clear()


def test_cliente_usa_timeout_de_leitura_de_30_segundos(cliente: httpx.AsyncClient) -> None:
    assert cliente.timeout.read == 30.0
    assert cliente.timeout.write == 30.0
    assert cliente.timeout.pool == 30.0


def test_cliente_mantem_timeout_de_conexao_curto(cliente: httpx.AsyncClient) -> None:
    assert cliente.timeout.connect == 5.0


def test_cliente_nao_usa_o_timeout_padrao_de_5_segundos_do_httpx(
    cliente: httpx.AsyncClient,
) -> None:
    assert cliente.timeout != httpx.Timeout(5.0)


def test_cliente_continua_apontando_para_a_api_do_storage_com_as_chaves_de_servico(
    cliente: httpx.AsyncClient,
) -> None:
    assert str(cliente.base_url) == "https://storage.teste/storage/v1/"
    assert cliente.headers["apikey"] == "chave-de-teste"
    assert cliente.headers["authorization"] == "Bearer chave-de-teste"


def test_cliente_e_reaproveitado_entre_chamadas(cliente: httpx.AsyncClient) -> None:
    assert get_storage_client() is cliente
