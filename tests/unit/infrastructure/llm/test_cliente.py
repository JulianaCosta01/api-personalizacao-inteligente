import pytest

from core.config import get_settings
from infrastructure.llm.cliente import get_gemini_client

# httpx resolve proxy do ambiente por padrão; em sandboxes com proxy SOCKS mas sem
# httpx[socks] instalado, só construir o Client já falha. Preparo do ambiente, não asserção.
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
    # get_gemini_client e get_settings são @lru_cache — limpar antes garante que o cliente é
    # reconstruído com o estado atual das variáveis de ambiente de teste, não de um teste anterior.
    get_gemini_client.cache_clear()
    get_settings.cache_clear()
    try:
        settings = get_settings()

        cliente = get_gemini_client()

        # Sem API pública para inspecionar retry de um Client construído — usamos os mesmos
        # atributos internos que o SDK usa para repassar HttpRetryOptions ao GeminiAdapter.
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
