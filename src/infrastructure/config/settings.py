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
    # Sem default, mesma razão do database_url: subir sem ele é falha de
    # config, não algo para mascarar com um valor de conveniência.
    service_token: str
    storage_url: str
    storage_service_key: str
    storage_bucket_materiais: str = "materiais-didaticos"
    material_tamanho_maximo_bytes: int = 10 * 1024 * 1024
    gemini_api_key: str
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_timeout_segundos: float = 5.0
    # Worker (Fase 7): intervalo entre tentativas de claim quando a fila está
    # vazia, e idade máxima de um Processamento em_processamento antes de ser
    # considerado preso e devolvido para pendente na recuperação de startup.
    worker_intervalo_polling_segundos: float = 5.0
    worker_idade_maxima_presos_segundos: float = 600.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
