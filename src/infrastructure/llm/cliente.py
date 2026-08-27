from functools import lru_cache

from google import genai
from google.genai import types

from core.config import get_settings


@lru_cache
def get_gemini_client() -> genai.Client:
    settings = get_settings()
    return genai.Client(
        api_key=settings.gemini_api_key,
        # Fase 8 Task 6: retry nativo do SDK (backoff exponencial + jitter),
        # não um loop manual — cobre tanto client.aio.models quanto
        # client.aio.interactions (usado pelo GeminiAdapter), que traduz este
        # HttpOptions.retry_options para sua própria configuração de retry.
        # Códigos retentáveis usam o default do SDK (408, 429, 5xx).
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(
                attempts=settings.gemini_retry_tentativas,
                initial_delay=settings.gemini_retry_atraso_inicial_segundos,
                max_delay=settings.gemini_retry_atraso_maximo_segundos,
                jitter=settings.gemini_retry_jitter_segundos,
            )
        ),
    )
