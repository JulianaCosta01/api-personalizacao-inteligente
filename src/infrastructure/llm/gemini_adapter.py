import asyncio
import logging

from google import genai

from application.ports.llm import ILLMPort
from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao

logger = logging.getLogger(__name__)

_SYSTEM_INSTRUCTION = (
    "Você é um assistente pedagógico. A partir das quatro dimensões do modelo "
    "Felder-Silverman informadas pelo usuário, escreva uma descrição curta e "
    "objetiva (no máximo duas frases) do estilo de aprendizagem do aluno. "
    "Responda apenas com a descrição, sem saudações ou comentários adicionais."
)
_TAMANHO_MAXIMO_RESPOSTA = 2000


class GeminiAdapter(ILLMPort):
    def __init__(self, cliente: genai.Client, modelo: str, timeout_segundos: float) -> None:
        self._cliente = cliente
        self._modelo = modelo
        self._timeout_segundos = timeout_segundos

    async def gerar_descricao_perfil(
        self,
        estilo_processamento: EstiloProcessamento,
        percepcao: Percepcao,
        entrada: Entrada,
        compreensao: Compreensao,
    ) -> str | None:
        entrada_usuario = (
            f"Estilo de processamento: {estilo_processamento.value}. "
            f"Percepção: {percepcao.value}. "
            f"Entrada: {entrada.value}. "
            f"Compreensão: {compreensao.value}."
        )
        try:
            interacao = await asyncio.wait_for(
                self._cliente.aio.interactions.create(
                    model=self._modelo,
                    system_instruction=_SYSTEM_INSTRUCTION,
                    input=entrada_usuario,
                    timeout=self._timeout_segundos,
                ),
                timeout=self._timeout_segundos,
            )
        except TimeoutError:
            logger.warning("Timeout ao chamar o Gemini para gerar descricao_llm.")
            return None
        except Exception as exc:
            # Nunca deixamos a exceção original subir: pode carregar detalhes
            # da requisição HTTP (headers, etc.) que não devem vazar por aqui.
            logger.warning("Falha ao chamar o Gemini (%s).", type(exc).__name__)
            return None

        return _validar_resposta(getattr(interacao, "output_text", None))


def _validar_resposta(texto: str | None) -> str | None:
    if not texto:
        return None
    texto = texto.strip()
    if not texto or len(texto) > _TAMANHO_MAXIMO_RESPOSTA:
        return None
    if _SYSTEM_INSTRUCTION.lower() in texto.lower():
        return None
    return texto
