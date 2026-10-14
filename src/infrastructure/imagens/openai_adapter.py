import asyncio
import base64
import binascii
import logging
import random
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
from infrastructure.config.settings import Settings

logger = logging.getLogger(__name__)

# Host fixo, nunca lido de configuração: a chave da API só pode seguir para ele (sem desvio de
# destino por variável de ambiente). Endpoint: POST {base}/images/generations.
_URL_BASE_OPENAI = "https://api.openai.com/v1"
_CAMINHO_GERACAO = "/images/generations"
_TIMEOUT_DE_CONEXAO_SEGUNDOS = 5.0

# Uma tentativa original + no máximo uma repetição, e só nos casos em que repetir é seguro e útil
# (ver _decidir_resposta). Cada repetição de uma geração aceita pode ser cobrada de novo.
_MAXIMO_DE_TENTATIVAS = 2
_ESPERA_PADRAO_ENTRE_TENTATIVAS_SEGUNDOS = 1.0
_ESPERA_MAXIMA_ENTRE_TENTATIVAS_SEGUNDOS = 10.0
_JITTER_MAXIMO_SEGUNDOS = 0.5

# O base64 ocupa ~4/3 do tamanho binário; recusa-se antes de decodificar para não alocar memória
# com uma resposta absurda.
_TAMANHO_MAXIMO_DO_BASE64 = (TAMANHO_MAXIMO_DA_IMAGEM_EM_BYTES * 4) // 3 + 8

# Códigos de erro 429 que indicam cota, crédito ou limite de gasto: repetir não resolve.
_CODIGOS_429_SEM_RETENTATIVA = frozenset(
    {
        "insufficient_quota",
        "credit_balance_exhausted",
        "organization_spend_limit_exceeded",
        "project_spend_limit_exceeded",
        "organization_usage_limit_exceeded",
    }
)
_STATUS_5XX_COM_RETENTATIVA = frozenset({500, 502, 503, 504})

# Texto enviado ao provedor: só este molde e a descrição visual curta do conceito. Nunca o título
# do material, dados do aluno, perfil de aprendizagem nem trechos do conteúdo.
_MOLDE_DO_PROMPT = (
    "Ilustração didática simples e limpa, em estilo de infográfico educacional, sem nenhum texto, "
    "letra, número, logotipo ou marca, e sem pessoas reais identificáveis. Representar: {descricao}"
)


class ErroDeConfiguracaoDeImagens(Exception):
    """A geração de imagens está desativada ou sem configuração completa.

    A mensagem nunca contém valores de configuração.
    """


class OpenAIImageAdapter(IGeradorDeImagens):
    def __init__(
        self,
        cliente: httpx.AsyncClient,
        modelo: str,
        qualidade: str,
        tamanho: str,
        timeout_segundos: float,
        timeout_total_segundos: float,
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not modelo.strip():
            raise ErroDeConfiguracaoDeImagens("Modelo de imagem não configurado.")
        self._cliente = cliente
        self._modelo = modelo
        self._qualidade = qualidade
        self._tamanho = tamanho
        # Tempo-limite de uma tentativa e orçamento total de uma geração (incluindo a repetição).
        self._timeout_segundos = timeout_segundos
        self._timeout_total_segundos = timeout_total_segundos
        self._dormir = dormir

    @classmethod
    def a_partir_de_settings(
        cls, settings: Settings, cliente: httpx.AsyncClient | None = None
    ) -> "OpenAIImageAdapter":
        # Recusa a criação, sem nenhuma chamada de rede, se o recurso estiver desligado ou sem
        # chave/modelo. Não há modelo padrão: o nome vem sempre da configuração.
        if not settings.imagens_geradas_habilitadas:
            raise ErroDeConfiguracaoDeImagens("Geração de imagens desativada.")
        if settings.openai_api_key is None:
            raise ErroDeConfiguracaoDeImagens("Chave da API de imagens não configurada.")
        if settings.openai_image_model is None:
            raise ErroDeConfiguracaoDeImagens("Modelo de imagem não configurado.")
        if cliente is None:
            cliente = httpx.AsyncClient(
                base_url=_URL_BASE_OPENAI,
                headers={"Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}"},
                timeout=httpx.Timeout(
                    settings.openai_image_timeout_segundos, connect=_TIMEOUT_DE_CONEXAO_SEGUNDOS
                ),
                follow_redirects=False,
            )
        return cls(
            cliente,
            settings.openai_image_model,
            settings.openai_image_quality,
            settings.openai_image_size,
            settings.openai_image_timeout_segundos,
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
            "model": self._modelo,
            "prompt": _MOLDE_DO_PROMPT.format(descricao=conceito.descricao),
            "n": 1,
            "size": self._tamanho,
            "quality": self._qualidade,
            "output_format": "png",
        }
        try:
            resposta = await self._cliente.post(
                _CAMINHO_GERACAO,
                json=corpo,
                timeout=httpx.Timeout(self._timeout_segundos, connect=_TIMEOUT_DE_CONEXAO_SEGUNDOS),
            )
        except httpx.ConnectTimeout:
            # Nada foi enviado ao serviço: seguro repetir.
            return self._falha(conceito, MotivoFalhaImagem.TIMEOUT), self._espera(None)
        except httpx.ConnectError:
            return self._falha(conceito, MotivoFalhaImagem.INDISPONIVEL), self._espera(None)
        except httpx.TimeoutException:
            # A requisição pode ter sido aceita (e cobrada): não repetir.
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

        codigo = _codigo_do_erro(resposta)
        if status == 429:
            if codigo in _CODIGOS_429_SEM_RETENTATIVA:
                return self._falha(conceito, MotivoFalhaImagem.LIMITE_EXCEDIDO), None
            return (
                self._falha(conceito, MotivoFalhaImagem.LIMITE_EXCEDIDO),
                self._espera(resposta.headers.get("retry-after")),
            )
        if status in _STATUS_5XX_COM_RETENTATIVA:
            return (
                self._falha(conceito, MotivoFalhaImagem.INDISPONIVEL),
                self._espera(resposta.headers.get("retry-after")),
            )
        if status == 400 and codigo is not None and _eh_recusa_de_conteudo(codigo):
            return self._falha(conceito, MotivoFalhaImagem.CONTEUDO_RECUSADO), None
        # Demais 4xx (requisição inválida, chave recusada, modelo inexistente) são problema de
        # configuração: repetir não ajuda.
        return self._falha(conceito, MotivoFalhaImagem.INDISPONIVEL), None

    def _extrair_imagem(
        self, conceito: ConceitoVisual, resposta: httpx.Response
    ) -> ResultadoGeracaoImagem:
        invalida = self._falha(conceito, MotivoFalhaImagem.RESPOSTA_INVALIDA)
        try:
            dados: Any = resposta.json()
            item = dados["data"][0]
            codificado = item["b64_json"]
        except (ValueError, KeyError, IndexError, TypeError):
            return invalida
        if not isinstance(codificado, str) or not codificado:
            return invalida
        if len(codificado) > _TAMANHO_MAXIMO_DO_BASE64:
            return invalida
        try:
            conteudo = base64.b64decode(codificado, validate=True)
        except (binascii.Error, ValueError):
            return invalida
        try:
            # O texto alternativo é a própria descrição do conceito (já validada).
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


def _codigo_do_erro(resposta: httpx.Response) -> str | None:
    # Lê só error.code do corpo de erro; o resto (mensagem, param) nunca é usado nem registrado.
    try:
        codigo = resposta.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return None
    return codigo if isinstance(codigo, str) else None


def _eh_recusa_de_conteudo(codigo: str) -> bool:
    minusculo = codigo.lower()
    return "moderation" in minusculo or "content_policy" in minusculo or "safety" in minusculo
