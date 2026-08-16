from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração do processo, carregada uma única vez por core.config.get_settings.

    Cresce a cada fase (DATABASE_URL na Fase 2, GEMINI_API_KEY na Fase 5 etc.) —
    por ora só o essencial para a aplicação subir.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    database_url: str
    # Token único de serviço (Documento 3, §2.2; Documento 4, §13.1) — sem
    # default, mesma razão do database_url: subir sem ele é falha de config,
    # não algo para mascarar com um valor de conveniência.
    service_token: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
