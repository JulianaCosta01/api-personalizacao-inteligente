from functools import lru_cache

from google import genai
from google.genai import types

from core.config import get_settings


@lru_cache
def get_gemini_client() -> genai.Client:
    settings = get_settings()
    return genai.Client(
        api_key=settings.gemini_api_key,
        # Retry nativo do SDK (backoff exponencial + jitter), cobre client.aio.interactions
        # (usado pelo GeminiAdapter). Códigos retentáveis: default do SDK.
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(
                attempts=settings.gemini_retry_tentativas,
                initial_delay=settings.gemini_retry_atraso_inicial_segundos,
                max_delay=settings.gemini_retry_atraso_maximo_segundos,
                jitter=settings.gemini_retry_jitter_segundos,
            )
        ),
    )
