from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração do processo, carregada uma única vez por core.config.get_settings."""

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
    # Documento 3 §7 exige URL assinada com expiração, valor não especificado ali;
    # default cobre uma sessão de leitura do Plugin abrindo/baixando o PDF.
    url_leitura_expiracao_segundos: int = 3600
    gemini_api_key: str
    gemini_model: str = "gemini-3.1-flash-lite"
    # Tempo-limite de cada tentativa individual ao Gemini (kwarg `timeout=` de
    # interactions.create, em segundos).
    gemini_timeout_segundos: float = 5.0
    # Repassado ao SDK google-genai via HttpRetryOptions (cliente.py); o retry é
    # executado pelo SDK, nunca um loop manual, e deve ficar limitado (DIRETRIZES_SEGURANCA §8).
    gemini_retry_tentativas: int = 3
    gemini_retry_atraso_inicial_segundos: float = 1.0
    gemini_retry_atraso_maximo_segundos: float = 8.0
    gemini_retry_jitter_segundos: float = 1.0
    # Orçamento total de uma chamada ao Gemini (todas as tentativas), usado só pelo
    # Worker; o caminho síncrono do Perfil segue limitado a gemini_timeout_segundos.
    gemini_timeout_total_segundos: float = 45.0
    # Intervalo entre tentativas de claim quando a fila está vazia, e idade máxima de
    # um Processamento em_processamento antes de ser considerado preso e reaberto no startup.
    worker_intervalo_polling_segundos: float = 5.0
    worker_idade_maxima_presos_segundos: float = 600.0
    # Rate limiting por token de serviço (Documento 4 §13.4), só nos dois endpoints de
    # maior custo/risco; Documento 4 não define o número exato, ajustável conforme uso real.
    rate_limit_processamentos_por_minuto: int = 10
    rate_limit_materiais_por_minuto: int = 20
    # CORS (Documento 4 §13.5): origens lidas do ambiente, nunca hardcoded. Vazia por
    # padrão, domínio real do Moodle não é inventado aqui; sem config, fica fail-closed.
    cors_origins_permitidas: list[str] = Field(default_factory=list)

    @property
    def cors_origins_efetivas(self) -> list[str]:
        """Resolve as origens de CORS por ambiente (Documento 4, §13.5).

        Se `cors_origins_permitidas` foi configurada, vale como está. Sem
        configuração: localhost em development, lista vazia (fail-closed) em
        qualquer outro ambiente — nunca um domínio de produção presumido aqui.
        """
        if self.cors_origins_permitidas:
            return self.cors_origins_permitidas
        if self.environment == "development":
            return ["http://localhost:3000", "http://localhost:8000"]
        return []


@lru_cache
def get_settings() -> Settings:
    return Settings()
