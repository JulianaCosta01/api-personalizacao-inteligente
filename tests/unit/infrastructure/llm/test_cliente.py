import pytest

from core.config import get_settings
from infrastructure.llm.cliente import get_gemini_client

# httpx (usado pelo SDK google-genai) resolve proxy a partir do ambiente por
# padrão. Em ambientes de execução com um proxy SOCKS configurado (comum em
# sandboxes de CI) e sem o extra `httpx[socks]` instalado, a simples
# construção de um Client — mesmo sem nenhuma chamada de rede — falha. Isso é
# uma particularidade do ambiente de execução, não do código sob teste, então
# é limpo aqui como preparação do teste, não como parte da asserção.
_VARIAVEIS_DE_PROXY = (
    "ALL_PROXY",
    "all_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
)


@pytest.fixture(autouse=True)
def _sem_proxy_no_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    for variavel in _VARIAVEIS_DE_PROXY:
        monkeypatch.delenv(variavel, raising=False)


def test_get_gemini_client_configura_retry_a_partir_das_settings() -> None:
    # get_gemini_client e get_settings são @lru_cache — limpar antes garante
    # que o cliente é reconstruído com o estado atual das variáveis de
    # ambiente de teste (tests/conftest.py), não uma instância de um teste
    # anterior.
    get_gemini_client.cache_clear()
    get_settings.cache_clear()
    try:
        settings = get_settings()

        cliente = get_gemini_client()

        # Não há API pública para inspecionar a configuração de retry de um
        # Client já construído; _api_client/_http_options são os mesmos
        # atributos que o próprio SDK usa internamente (ver
        # google.genai._gaos.google_genai.build_google_genai_async_client)
        # para repassar HttpRetryOptions ao client.aio.interactions usado
        # pelo GeminiAdapter.
        retry_options = cliente._api_client._http_options.retry_options
        assert retry_options is not None
        assert retry_options.attempts == settings.gemini_retry_tentativas
        assert retry_options.initial_delay == settings.gemini_retry_atraso_inicial_segundos
        assert retry_options.max_delay == settings.gemini_retry_atraso_maximo_segundos
        assert retry_options.jitter == settings.gemini_retry_jitter_segundos
    finally:
        get_gemini_client.cache_clear()
        get_settings.cache_clear()


def test_get_gemini_client_e_cacheado() -> None:
    get_gemini_client.cache_clear()
    try:
        assert get_gemini_client() is get_gemini_client()
    finally:
        get_gemini_client.cache_clear()
