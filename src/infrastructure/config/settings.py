from functools import lru_cache
from typing import Literal

from pydantic import Field
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
    # Documento 3 §7 exige URL assinada com expiração para caminho_pdf do
    # Material Personalizado, mas não especifica o valor — default de
    # implementação (Fase 8), tempo suficiente para o Plugin abrir/baixar o
    # PDF numa única sessão de leitura.
    url_leitura_expiracao_segundos: int = 3600
    gemini_api_key: str
    gemini_model: str = "gemini-3.1-flash-lite"
    # Tempo-limite de CADA tentativa individual ao Gemini (kwarg `timeout=` de
    # interactions.create, em segundos) — não muda de sentido na Fase 8 Task 6.
    gemini_timeout_segundos: float = 5.0
    # Fase 8 Task 6 — resiliência: número de tentativas (incluindo a
    # original) e forma do backoff entre elas, repassados ao SDK google-genai
    # via HttpRetryOptions (infrastructure/llm/cliente.py). O retry em si é
    # executado pelo SDK — nenhum loop manual é implementado aqui.
    # DIRETRIZES_DESENVOLVIMENTO_SEGURANCA.md §8 exige que esse retry seja
    # limitado (nunca um loop sem fim); os defaults abaixo refletem isso.
    gemini_retry_tentativas: int = 3
    gemini_retry_atraso_inicial_segundos: float = 1.0
    gemini_retry_atraso_maximo_segundos: float = 8.0
    gemini_retry_jitter_segundos: float = 1.0
    # Orçamento total de UMA chamada ao Gemini, incluindo todas as tentativas
    # de retry acima — usado apenas pelo Worker (caminho assíncrono, sem
    # requisição HTTP bloqueada à espera). O caminho síncrono do Perfil
    # continua limitado a gemini_timeout_segundos (Documento 3 §4.2 exige
    # tempo-limite curto ali; ver presentation/api/routers/perfil.py). Default
    # calculado para o pior caso: 3 tentativas x 5s (timeout por tentativa) +
    # até ~8s de backoff entre elas, com folga.
    gemini_timeout_total_segundos: float = 45.0
    # Worker (Fase 7): intervalo entre tentativas de claim quando a fila está
    # vazia, e idade máxima de um Processamento em_processamento antes de ser
    # considerado preso e devolvido para pendente na recuperação de startup.
    worker_intervalo_polling_segundos: float = 5.0
    worker_idade_maxima_presos_segundos: float = 600.0
    # Fase 9 Task 1 — rate limiting por token de serviço (Documento 4, §13.4),
    # aplicado só nos dois endpoints de maior custo/risco de abuso. Documento
    # 4 não define o número exato; defaults de implementação, ajustáveis
    # conforme uso real medido (ver presentation/api/rate_limit.py).
    rate_limit_processamentos_por_minuto: int = 10
    rate_limit_materiais_por_minuto: int = 20
    # Fase 9 Task 3 — CORS (Documento 4, §13.5). Lista de origens
    # explicitamente permitidas, lida do ambiente (JSON), nunca hardcoded no
    # middleware. Vazia por padrão: o domínio real do Moodle da UFMA não é
    # inventado aqui (não especificado em nenhum documento) — enquanto não
    # for configurado, o comportamento é fail-closed (ver
    # `cors_origins_efetivas` abaixo).
    cors_origins_permitidas: list[str] = Field(default_factory=list)

    @property
    def cors_origins_efetivas(self) -> list[str]:
        """Resolve as origens de CORS por ambiente (Documento 4, §13.5).

        Se `cors_origins_permitidas` foi configurada explicitamente, vale tal
        como está, em qualquer ambiente. Sem configuração explícita: em
        development, usa defaults locais de conveniência (localhost); em
        qualquer outro ambiente, a lista fica vazia — fail-closed, nunca um
        domínio de produção presumido por este código.
        """
        if self.cors_origins_permitidas:
            return self.cors_origins_permitidas
        if self.environment == "development":
            return ["http://localhost:3000", "http://localhost:8000"]
        return []


@lru_cache
def get_settings() -> Settings:
    return Settings()
