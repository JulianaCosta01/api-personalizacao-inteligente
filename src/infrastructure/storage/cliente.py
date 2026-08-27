from functools import lru_cache

import httpx

from core.config import get_settings


@lru_cache
def get_storage_client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=f"{settings.storage_url}/storage/v1",
        headers={
            "apikey": settings.storage_service_key,
            "Authorization": f"Bearer {settings.storage_service_key}",
        },
    )
