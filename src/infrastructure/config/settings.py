import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from infrastructure.imagens.prazo_total import MARGEM_MINIMA_PARA_INICIAR_SEGUNDOS

# Cloudflare: o ID da conta e o nome do modelo entram no CAMINHO da URL da API, então só o formato
# conhecido é aceito (nunca um valor livre). ID de conta: 32 caracteres hexadecimais.
PADRAO_ID_DE_CONTA_CLOUDFLARE = re.compile(r"[0-9a-fA-F]{32}")
PADRAO_MODELO_CLOUDFLARE = re.compile(r"@cf/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*")


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
    # Teto do corpo das demais requisições da API (JSON), aplicado antes de qualquer parse. O do
    # upload de material é material_tamanho_maximo_bytes mais a folga do multipart.
    corpo_json_tamanho_maximo_bytes: int = Field(default=1024 * 1024, gt=0, le=10 * 1024 * 1024)
    # Limites de consumo do pipeline sobre PDFs não confiáveis: o tamanho em bytes não limita a
    # quantidade de páginas nem o tamanho decodificado de uma imagem (um PDF pequeno pode
    # declarar uma imagem de bilhões de pixels).
    pdf_paginas_maximas: int = Field(default=100, ge=1, le=1000)
    pdf_pixels_maximos_por_imagem: int = Field(default=25_000_000, ge=1)
    # URL assinada precisa expirar; o padrão cobre uma sessão de leitura do Plugin
    # abrindo/baixando o PDF.
    url_leitura_expiracao_segundos: int = 3600
    gemini_api_key: str
    gemini_model: str = "gemini-3.1-flash-lite"
    # Tempo-limite de cada tentativa individual ao Gemini (kwarg `timeout=` de
    # interactions.create, em segundos).
    gemini_timeout_segundos: float = 5.0
    # Repassado ao SDK google-genai via HttpRetryOptions (cliente.py); o retry é
    # executado pelo SDK, nunca um loop manual, e deve ficar limitado.
    gemini_retry_tentativas: int = 3
    gemini_retry_atraso_inicial_segundos: float = 1.0
    gemini_retry_atraso_maximo_segundos: float = 8.0
    gemini_retry_jitter_segundos: float = 1.0
    # Orçamento total de uma chamada ao Gemini (todas as tentativas), usado só pelo
    # Worker; o caminho síncrono do Perfil segue limitado a gemini_timeout_segundos.
    gemini_timeout_total_segundos: float = 45.0
    # Reescrita curta ou incompleta (ver GeminiAdapter._motivo_de_insuficiencia): quantas chamadas
    # EXTRAS ao modelo são permitidas para obter uma versão completa (0 desliga) e a proporção
    # mínima da resposta em relação ao tamanho do original abaixo da qual ela é "curta".
    gemini_reescrita_complemento_tentativas: int = Field(default=1, ge=0, le=2)
    gemini_reescrita_proporcao_minima: float = Field(default=0.8, gt=0, le=3.0)
    # Limites das etapas locais do Worker (CPU, sem rede), separados do timeout do Gemini.
    # Estourar um deles encerra o job em erro, sem repetir a chamada paga ao modelo.
    pipeline_timeout_extracao_segundos: float = Field(default=30.0, gt=0)
    pipeline_timeout_pdf_segundos: float = Field(default=60.0, gt=0)
    # As imagens do PDF de origem não substituem as ilustrações geradas por IA: por padrão não são
    # extraídas nem anexadas ao material. Ligar só se o material original precisar delas ao final.
    pdf_anexar_imagens_originais: bool = False
    # Geração de imagens por IA (Cloudflare Workers AI): desligada por padrão. As credenciais e o
    # modelo da Cloudflare são opcionais enquanto a flag estiver desligada, para não exigir
    # configuração nova de quem não usa o recurso; ligar a flag sem eles falha na inicialização.
    imagens_geradas_habilitadas: bool = False
    # Teto de UMA imagem, incluindo a repetição. O tempo-limite de uma tentativa é
    # CLOUDFLARE_IMAGE_TIMEOUT_SEGUNDOS, e este valor não pode ser menor que ele.
    imagens_timeout_total_segundos: float = Field(default=120.0, gt=0, le=600)
    # Orçamento compartilhado por todas as imagens de um material: começa uma vez e não reinicia
    # a cada imagem. Abaixo da margem mínima para iniciar uma geração nenhuma imagem seria feita.
    imagens_orcamento_total_segundos: float = Field(
        default=150.0, ge=MARGEM_MINIMA_PARA_INICIAR_SEGUNDOS, le=600
    )
    imagens_max_por_material: int = Field(default=1, ge=1, le=5)
    # Único provedor de imagens suportado: Cloudflare Workers AI. O campo existe para que a variável
    # IMAGENS_PROVEDOR=cloudflare continue válida; qualquer outro valor falha na inicialização.
    # As credenciais abaixo só são exigidas com o recurso LIGADO.
    imagens_provedor: Literal["cloudflare"] = "cloudflare"
    cloudflare_account_id: str | None = None
    cloudflare_api_token: SecretStr | None = None
    # Nenhum modelo é presumido. Ex.: @cf/black-forest-labs/flux-1-schnell.
    cloudflare_image_model: str | None = None
    # Passos de difusão do FLUX.1 schnell: máximo 8 (documentação); mais passos, mais Neurons.
    cloudflare_image_steps: int = Field(default=4, ge=1, le=8)
    # Tempo-limite de uma tentativa; o teto de UMA imagem segue em IMAGENS_TIMEOUT_TOTAL_SEGUNDOS.
    cloudflare_image_timeout_segundos: float = Field(default=60.0, gt=0, le=300)
    # Intervalo entre tentativas de claim quando a fila está vazia, e idade máxima de
    # um Processamento em_processamento antes de ser considerado preso e reaberto no startup.
    worker_intervalo_polling_segundos: float = 5.0
    worker_idade_maxima_presos_segundos: float = 600.0
    # Prazo máximo de UM job (da reivindicação ao fim): estourado, o job é cancelado e termina em
    # erro. Precisa ser menor que a idade em que a recuperação considera o job preso, senão a
    # recuperação poderia devolvê-lo à fila enquanto ainda roda.
    worker_prazo_maximo_job_segundos: float = Field(default=420.0, gt=0)
    # Quantas vezes um Processamento pode ser reivindicado; ao esgotar, vai para erro.
    worker_tentativas_maximas: int = Field(default=3, ge=1, le=10)
    # Espera entre reivindicações quando o job volta à fila por falha transitória do Gemini
    # (503, 429, timeout): base * 2^(n-1), limitada pelo teto, com jitter que só reduz o atraso.
    # Com os padrões e 3 reivindicações, o pior caso de espera é 30 s + 60 s.
    worker_repeticao_atraso_base_segundos: float = Field(default=30.0, gt=0)
    worker_repeticao_atraso_maximo_segundos: float = Field(default=300.0, gt=0)
    # Rate limiting por token de serviço, só nos endpoints de maior custo/risco.
    # Valores iniciais, ajustáveis conforme o uso real.
    rate_limit_processamentos_por_minuto: int = 10
    rate_limit_materiais_por_minuto: int = 20
    # POST /perfil chama o Gemini de forma síncrona: o custo de cada chamada justifica o teto.
    rate_limit_perfis_por_minuto: int = 20
    # Origens de CORS vêm do ambiente, nunca hardcoded. Vazia por padrão (fail-closed):
    # o domínio real do Moodle não é inventado aqui.
    cors_origins_permitidas: list[str] = Field(default_factory=list)

    @field_validator(
        "cloudflare_account_id",
        "cloudflare_api_token",
        "cloudflare_image_model",
        mode="before",
    )
    @classmethod
    def _vazio_equivale_a_ausente(cls, valor: object) -> object:
        # `CLOUDFLARE_API_TOKEN=` vazio no .env/.env.example vale como "não configurada".
        if isinstance(valor, str) and not valor.strip():
            return None
        return valor

    @model_validator(mode="after")
    def _imagens_habilitadas_exigem_configuracao_completa(self) -> "Settings":
        # As mensagens nomeiam só as variáveis, nunca os valores (que podem ser segredos).
        if self.imagens_geradas_habilitadas:
            if self.cloudflare_account_id is None:
                raise ValueError(
                    "CLOUDFLARE_ACCOUNT_ID é obrigatório com IMAGENS_PROVEDOR=cloudflare."
                )
            if PADRAO_ID_DE_CONTA_CLOUDFLARE.fullmatch(self.cloudflare_account_id) is None:
                raise ValueError(
                    "CLOUDFLARE_ACCOUNT_ID deve ter 32 caracteres hexadecimais "
                    "(confira se o valor foi copiado por inteiro, sem espaços ou aspas)."
                )
            if self.cloudflare_api_token is None:
                raise ValueError(
                    "CLOUDFLARE_API_TOKEN é obrigatório com IMAGENS_PROVEDOR=cloudflare."
                )
            if self.cloudflare_image_model is None:
                raise ValueError(
                    "CLOUDFLARE_IMAGE_MODEL é obrigatório com IMAGENS_PROVEDOR=cloudflare."
                )
            if PADRAO_MODELO_CLOUDFLARE.fullmatch(self.cloudflare_image_model) is None:
                raise ValueError("CLOUDFLARE_IMAGE_MODEL deve ter o formato @cf/<autor>/<modelo>.")
        if self.imagens_timeout_total_segundos < self.cloudflare_image_timeout_segundos:
            raise ValueError(
                "IMAGENS_TIMEOUT_TOTAL_SEGUNDOS não pode ser menor que "
                "CLOUDFLARE_IMAGE_TIMEOUT_SEGUNDOS."
            )
        return self

    @model_validator(mode="after")
    def _prazo_do_job_menor_que_a_recuperacao(self) -> "Settings":
        if self.worker_prazo_maximo_job_segundos >= self.worker_idade_maxima_presos_segundos:
            raise ValueError(
                "WORKER_PRAZO_MAXIMO_JOB_SEGUNDOS deve ser menor que "
                "WORKER_IDADE_MAXIMA_PRESOS_SEGUNDOS."
            )
        return self

    @model_validator(mode="after")
    def _etapas_de_uma_execucao_cabem_no_prazo_do_job(self) -> "Settings":
        # Pior caso de espera de uma execução: extração, Gemini com retries, montagem do PDF e,
        # se ligadas, imagens geradas e a segunda montagem. Só confere a coerência da config: o teto
        # real é o prazo do job no Worker, e Storage e banco consomem a folga.
        extracoes = 2 if self.pdf_anexar_imagens_originais else 1
        pior_caso = (
            extracoes * self.pipeline_timeout_extracao_segundos
            + self.gemini_timeout_total_segundos
            * (1 + self.gemini_reescrita_complemento_tentativas)
            + self.pipeline_timeout_pdf_segundos
        )
        if self.imagens_geradas_habilitadas:
            pior_caso += self.imagens_orcamento_total_segundos + self.pipeline_timeout_pdf_segundos
        if pior_caso > self.worker_prazo_maximo_job_segundos:
            raise ValueError(
                "A soma dos limites das etapas de um job "
                f"({pior_caso:.0f} s) excede WORKER_PRAZO_MAXIMO_JOB_SEGUNDOS "
                f"({self.worker_prazo_maximo_job_segundos:.0f} s)."
            )
        return self

    @model_validator(mode="after")
    def _atraso_de_repeticao_coerente(self) -> "Settings":
        if (
            self.worker_repeticao_atraso_maximo_segundos
            < self.worker_repeticao_atraso_base_segundos
        ):
            raise ValueError(
                "WORKER_REPETICAO_ATRASO_MAXIMO_SEGUNDOS não pode ser menor que "
                "WORKER_REPETICAO_ATRASO_BASE_SEGUNDOS."
            )
        return self

    @property
    def cors_origins_efetivas(self) -> list[str]:
        """Resolve as origens de CORS por ambiente.

        Se `cors_origins_permitidas` foi configurada, vale como está. Sem
        configuração: localhost em development, lista vazia (fail-closed) em
        qualquer outro ambiente, nunca um domínio de produção presumido aqui.
        """
        if self.cors_origins_permitidas:
            return self.cors_origins_permitidas
        if self.environment == "development":
            return ["http://localhost:3000", "http://localhost:8000"]
        return []


@lru_cache
def get_settings() -> Settings:
    return Settings()
