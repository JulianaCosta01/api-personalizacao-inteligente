from functools import lru_cache

import httpx

from core.config import get_settings

# Sem timeout explícito o httpx usa 5 s em todas as fases, curto demais para a assinatura de URL
# logo após o Supabase "acordar" (ReadTimeout observado em criar_url_leitura) e para upload e
# download de PDFs maiores. Conexão continua curta: falha rápida se o host não responde.
_TIMEOUT_STORAGE = httpx.Timeout(30.0, connect=5.0)


@lru_cache
def get_storage_client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=f"{settings.storage_url}/storage/v1",
        timeout=_TIMEOUT_STORAGE,
        headers={
            "apikey": settings.storage_service_key,
            "Authorization": f"Bearer {settings.storage_service_key}",
        },
    )
