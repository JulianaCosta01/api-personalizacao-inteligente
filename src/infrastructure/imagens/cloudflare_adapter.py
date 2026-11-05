import asyncio
import base64
import binascii
import logging
import random
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from application.ports.gerador_imagens import (
    TAMANHO_MAXIMO_DA_IMAGEM_EM_BYTES,
    ConceitoVisual,
    FalhaGeracaoImagem,
    IGeradorDeImagens,
    ImagemGerada,
    MotivoFalhaImagem,
    ResultadoGeracaoImagem,
)
from domain.shared.exceptions import EntradaInvalidaError
from infrastructure.config.settings import (
    PADRAO_ID_DE_CONTA_CLOUDFLARE,
    PADRAO_MODELO_CLOUDFLARE,
    Settings,
)

logger = logging.getLogger(__name__)

# Host fixo, nunca lido de configuração: o token da API só pode seguir para ele (sem desvio de
# destino por variável de ambiente). Endpoint: POST {base}/accounts/{conta}/ai/run/{modelo}.
_URL_BASE_CLOUDFLARE = "https://api.cloudflare.com/client/v4"
_TIMEOUT_DE_CONEXAO_SEGUNDOS = 5.0

# Uma tentativa original + no máximo uma repetição, e só quando repetir é seguro (conexão que nem
# chegou ao serviço, ou 5xx). 429 e demais 4xx nunca repetem: o 429 pode ser a cota diária do
# plano gratuito (10.000 Neurons por dia), que repetir não resolve.
_MAXIMO_DE_TENTATIVAS = 2
_ESPERA_PADRAO_ENTRE_TENTATIVAS_SEGUNDOS = 1.0
_ESPERA_MAXIMA_ENTRE_TENTATIVAS_SEGUNDOS = 10.0
_JITTER_MAXIMO_SEGUNDOS = 0.5
_STATUS_5XX_COM_RETENTATIVA = frozenset({500, 502, 503, 504})

# O base64 ocupa ~4/3 do tamanho binário; recusa-se antes de decodificar para não alocar memória
# com uma resposta absurda.
_TAMANHO_MAXIMO_DO_BASE64 = (TAMANHO_MAXIMO_DA_IMAGEM_EM_BYTES * 4) // 3 + 8

# Limite do campo `prompt` do FLUX.1 schnell (documentação do Workers AI).
TAMANHO_MAXIMO_DO_PROMPT = 2048

# Texto enviado ao provedor: só este molde e a descrição visual curta do conceito. Nunca o título
# do material, dados do aluno, perfil de aprendizagem nem trechos do conteúdo. O molde é em inglês
# porque o modelo é treinado sobretudo nessa língua; a descrição segue como o Gemini a escreveu.
_MOLDE_DO_PROMPT = (
    "Simple, clean educational illustration in the style of an infographic, with no text, "
    "letters, numbers, logos or watermarks, and no recognizable real people. Depict: {descricao}"
)


_PADRAO_CONTA_NA_URL = re.compile(r"/accounts/[^/\s\"]+/")


class _OcultaIdDaContaNosLogsDoHttpx(logging.Filter):
    """Troca o ID da conta, que viaja no caminho da URL, antes de o httpx registrá-la.

    O httpx registra (INFO) a URL de cada requisição, e o ID da conta faria parte dela. O token
    vai em cabeçalho e nunca aparece ali; o ID não é segredo, mas não há razão para ele ir parar
    em logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        mensagem = record.getMessage()
        if "/accounts/" in mensagem:
            record.msg = _PADRAO_CONTA_NA_URL.sub("/accounts/<conta>/", mensagem)
            record.args = None
        return True


def _ocultar_id_da_conta_nos_logs_do_httpx() -> None:
    logger_httpx = logging.getLogger("httpx")
    if not any(isinstance(f, _OcultaIdDaContaNosLogsDoHttpx) for f in logger_httpx.filters):
        logger_httpx.addFilter(_OcultaIdDaContaNosLogsDoHttpx())


class ErroDeConfiguracaoDeImagensCloudflare(Exception):
    """A geração de imagens da Cloudflare está desativada ou sem configuração completa.

    A mensagem nunca contém valores de configuração.
    """


class CloudflareImageAdapter(IGeradorDeImagens):
    def __init__(
        self,
        cliente: httpx.AsyncClient,
        id_da_conta: str,
        modelo: str,
        passos: int,
        timeout_segundos: float,
        timeout_total_segundos: float,
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        # O ID da conta e o modelo viram partes do caminho da URL: só o formato conhecido passa.
        if PADRAO_ID_DE_CONTA_CLOUDFLARE.fullmatch(id_da_conta) is None:
            raise ErroDeConfiguracaoDeImagensCloudflare("ID da conta Cloudflare inválido.")
        if PADRAO_MODELO_CLOUDFLARE.fullmatch(modelo) is None:
            raise ErroDeConfiguracaoDeImagensCloudflare("Modelo de imagem inválido.")
        _ocultar_id_da_conta_nos_logs_do_httpx()
        self._cliente = cliente
        self._caminho = f"/accounts/{id_da_conta}/ai/run/{modelo}"
        self._passos = passos
        # Tempo-limite de uma tentativa e orçamento total de uma geração (incluindo a repetição).
        self._timeout_segundos = timeout_segundos
        self._timeout_total_segundos = timeout_total_segundos
        self._dormir = dormir

    @classmethod
    def a_partir_de_settings(
        cls, settings: Settings, cliente: httpx.AsyncClient | None = None
    ) -> "CloudflareImageAdapter":
        # Recusa a criação, sem nenhuma chamada de rede, se o recurso estiver desligado ou se
        # faltar credencial/modelo. Não há modelo padrão.
        if not settings.imagens_geradas_habilitadas:
            raise ErroDeConfiguracaoDeImagensCloudflare("Geração de imagens desativada.")
        if settings.cloudflare_account_id is None:
            raise ErroDeConfiguracaoDeImagensCloudflare("ID da conta Cloudflare não configurado.")
        if settings.cloudflare_api_token is None:
            raise ErroDeConfiguracaoDeImagensCloudflare("Token da Cloudflare não configurado.")
        if settings.cloudflare_image_model is None:
            raise ErroDeConfiguracaoDeImagensCloudflare("Modelo de imagem não configurado.")
        if cliente is None:
            cliente = httpx.AsyncClient(
                base_url=_URL_BASE_CLOUDFLARE,
                headers={
                    "Authorization": (f"Bearer {settings.cloudflare_api_token.get_secret_value()}")
                },
                timeout=httpx.Timeout(
                    settings.cloudflare_image_timeout_segundos,
                    connect=_TIMEOUT_DE_CONEXAO_SEGUNDOS,
                ),
                follow_redirects=False,
            )
        return cls(
            cliente,
            settings.cloudflare_account_id,
            settings.cloudflare_image_model,
            settings.cloudflare_image_steps,
            settings.cloudflare_image_timeout_segundos,
            settings.imagens_timeout_total_segundos,
        )

    async def gerar(self, conceito: ConceitoVisual) -> ResultadoGeracaoImagem:
        try:
            resultado = await asyncio.wait_for(
                self._gerar_com_retentativa(conceito), timeout=self._timeout_total_segundos
            )
        except (TimeoutError, asyncio.TimeoutError):  # noqa: UP041 - distintos antes do Python 3.11
            resultado = self._falha(conceito, MotivoFalhaImagem.TIMEOUT)
        except Exception as exc:
            # Só o nome da classe: a exceção original pode carregar URL, headers ou o prompt.
            logger.warning("Falha inesperada ao gerar imagem (%s).", type(exc).__name__)
            resultado = self._falha(conceito, MotivoFalhaImagem.INDISPONIVEL)
        if isinstance(resultado, FalhaGeracaoImagem):
            logger.warning(
                "Imagem não gerada (conceito=%s, motivo=%s).",
                conceito.identificador,
                resultado.motivo.value,
            )
        return resultado

    async def _gerar_com_retentativa(self, conceito: ConceitoVisual) -> ResultadoGeracaoImagem:
        for tentativa in range(1, _MAXIMO_DE_TENTATIVAS + 1):
            resultado, espera = await self._tentar_uma_vez(conceito)
            if espera is None or tentativa == _MAXIMO_DE_TENTATIVAS:
                return resultado
            await self._dormir(espera)
        raise AssertionError("inalcançável")  # pragma: no cover

    async def _tentar_uma_vez(
        self, conceito: ConceitoVisual
    ) -> tuple[ResultadoGeracaoImagem, float | None]:
        # Devolve (resultado, espera): espera != None significa "vale repetir depois desse tempo".
        corpo = {
            "prompt": _MOLDE_DO_PROMPT.format(descricao=conceito.descricao),
            "steps": self._passos,
        }
        try:
            resposta = await self._cliente.post(
                self._caminho,
                json=corpo,
                timeout=httpx.Timeout(self._timeout_segundos, connect=_TIMEOUT_DE_CONEXAO_SEGUNDOS),
            )
        except httpx.ConnectTimeout:
            # Nada foi enviado ao serviço: seguro repetir.
            return self._falha(conceito, MotivoFalhaImagem.TIMEOUT), self._espera(None)
        except httpx.ConnectError:
            return self._falha(conceito, MotivoFalhaImagem.INDISPONIVEL), self._espera(None)
        except httpx.TimeoutException:
            # A requisição pode ter sido aceita (e consumido Neurons): não repetir.
            return self._falha(conceito, MotivoFalhaImagem.TIMEOUT), None
        except httpx.HTTPError as exc:
            logger.warning("Erro de transporte ao gerar imagem (%s).", type(exc).__name__)
            return self._falha(conceito, MotivoFalhaImagem.INDISPONIVEL), None
        return self._decidir_resposta(conceito, resposta)

    def _decidir_resposta(
        self, conceito: ConceitoVisual, resposta: httpx.Response
    ) -> tuple[ResultadoGeracaoImagem, float | None]:
        status = resposta.status_code
        if status == 200:
            return self._extrair_imagem(conceito, resposta), None
        if status == 429:
            # Cota diária esgotada ou limite de taxa: o corpo não é lido nem registrado, e repetir
            # não ajuda (a cota só volta às 00:00 UTC).
            return self._falha(conceito, MotivoFalhaImagem.LIMITE_EXCEDIDO), None
        if status in _STATUS_5XX_COM_RETENTATIVA:
            return (
                self._falha(conceito, MotivoFalhaImagem.INDISPONIVEL),
                self._espera(resposta.headers.get("retry-after")),
            )
        # Demais 4xx (requisição inválida, token recusado, modelo ou conta inexistente) são
        # problema de configuração: repetir não ajuda.
        return self._falha(conceito, MotivoFalhaImagem.INDISPONIVEL), None

    def _extrair_imagem(
        self, conceito: ConceitoVisual, resposta: httpx.Response
    ) -> ResultadoGeracaoImagem:
        invalida = self._falha(conceito, MotivoFalhaImagem.RESPOSTA_INVALIDA)
        try:
            dados: Any = resposta.json()
            if dados.get("success") is False:
                return invalida
            codificado = dados["result"]["image"]
        except (ValueError, KeyError, TypeError, AttributeError):
            return invalida
        if not isinstance(codificado, str) or not codificado:
            return invalida
        if len(codificado) > _TAMANHO_MAXIMO_DO_BASE64:
            return invalida
        try:
            # Espaços e quebras de linha são tolerados (alguns serviços quebram o base64); qualquer
            # outro caractere fora do alfabeto continua sendo recusado (validate=True).
            conteudo = base64.b64decode("".join(codificado.split()), validate=True)
        except (binascii.Error, ValueError):
            return invalida
        try:
            # O texto alternativo é a própria descrição do conceito (já validada). A validação
            # de formato (PNG/JPEG), estrutura e tamanho é a de ImagemGerada.
            return ImagemGerada(conteudo=conteudo, texto_alternativo=conceito.descricao)
        except EntradaInvalidaError:
            return invalida

    @staticmethod
    def _falha(conceito: ConceitoVisual, motivo: MotivoFalhaImagem) -> FalhaGeracaoImagem:
        return FalhaGeracaoImagem(conceito.identificador, motivo)

    @staticmethod
    def _espera(retry_after: str | None) -> float:
        espera = _ESPERA_PADRAO_ENTRE_TENTATIVAS_SEGUNDOS
        if (
            retry_after is not None
            and retry_after.strip().isascii()
            and retry_after.strip().isdigit()
        ):
            espera = float(retry_after.strip())
        espera = min(espera, _ESPERA_MAXIMA_ENTRE_TENTATIVAS_SEGUNDOS)
        return espera + random.uniform(0, _JITTER_MAXIMO_SEGUNDOS)
