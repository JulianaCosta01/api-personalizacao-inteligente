import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from infrastructure.imagens.prazo_total import MARGEM_MINIMA_PARA_INICIAR_SEGUNDOS

_PADRAO_TAMANHO_DE_IMAGEM = re.compile(r"[1-9][0-9]{2,4}x[1-9][0-9]{2,4}")


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
    # Geração de imagens por IA (OpenAI): desligada por padrão. A chave e o modelo são opcionais
    # enquanto a flag estiver desligada, para não exigir configuração nova de quem não usa o
    # recurso; ligar a flag sem eles falha na inicialização. Nenhum modelo é fixado aqui: o
    # nome é escolhido na configuração (e confirmado contra a documentação da API) por quem liga.
    imagens_geradas_habilitadas: bool = False
    openai_api_key: SecretStr | None = None
    openai_image_model: str | None = None
    # Valores aceitos variam por modelo; aqui só o formato é validado (ver validador abaixo).
    # Padrões conservadores quanto a custo.
    openai_image_quality: Literal["auto", "low", "medium", "high"] = "low"
    openai_image_size: str = "1024x1024"
    # Tempo-limite de uma tentativa de geração e teto de UMA imagem (incluindo a repetição).
    openai_image_timeout_segundos: float = Field(default=60.0, gt=0, le=300)
    imagens_timeout_total_segundos: float = Field(default=120.0, gt=0, le=600)
    # Orçamento compartilhado por todas as imagens de um material: começa uma vez e não reinicia
    # a cada imagem. Abaixo da margem mínima para iniciar uma geração nenhuma imagem seria feita.
    imagens_orcamento_total_segundos: float = Field(
        default=150.0, ge=MARGEM_MINIMA_PARA_INICIAR_SEGUNDOS, le=600
    )
    imagens_max_por_material: int = Field(default=1, ge=1, le=5)
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

    @field_validator("openai_api_key", "openai_image_model", mode="before")
    @classmethod
    def _vazio_equivale_a_ausente(cls, valor: object) -> object:
        # `OPENAI_API_KEY=` vazio no .env/.env.example vale como "não configurada".
        if isinstance(valor, str) and not valor.strip():
            return None
        return valor

    @field_validator("openai_image_size")
    @classmethod
    def _tamanho_de_imagem_com_formato_valido(cls, valor: str) -> str:
        if valor != "auto" and _PADRAO_TAMANHO_DE_IMAGEM.fullmatch(valor) is None:
            raise ValueError("Use 'auto' ou LARGURAxALTURA em pixels (ex.: 1024x1024).")
        return valor

    @model_validator(mode="after")
    def _imagens_habilitadas_exigem_configuracao_completa(self) -> "Settings":
        if self.imagens_geradas_habilitadas:
            if self.openai_api_key is None:
                raise ValueError("OPENAI_API_KEY é obrigatória com IMAGENS_GERADAS_HABILITADAS.")
            if self.openai_image_model is None:
                raise ValueError(
                    "OPENAI_IMAGE_MODEL é obrigatório com IMAGENS_GERADAS_HABILITADAS."
                )
        if self.imagens_timeout_total_segundos < self.openai_image_timeout_segundos:
            raise ValueError(
                "IMAGENS_TIMEOUT_TOTAL_SEGUNDOS não pode ser menor que "
                "OPENAI_IMAGE_TIMEOUT_SEGUNDOS."
            )
        return self

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
