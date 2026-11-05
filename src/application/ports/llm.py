from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao


@dataclass
class ConteudoPersonalizado:
    conteudo_pdf: bytes
    resumo: str


class CategoriaFalhaTransitoria(StrEnum):
    # Valores estáveis: aparecem nos logs. Nunca carregam texto do provedor.
    TIMEOUT_TOTAL = "timeout_total"
    HTTP_408 = "http_408"
    HTTP_429 = "http_429"
    HTTP_5XX = "http_5xx"
    REDE = "rede"


class FalhaTransitoriaDoProvedorError(Exception):
    """Falha do provedor que costuma passar sozinha (indisponibilidade, limite de taxa, timeout).

    Só a chamada ao modelo em `reescrever_conteudo` a levanta. Carrega a categoria e o código
    HTTP, nunca a mensagem ou o corpo da resposta.
    """

    def __init__(self, categoria: CategoriaFalhaTransitoria, status_http: int | None = None):
        self.categoria = categoria
        self.status_http = status_http
        super().__init__(f"Falha transitória do provedor de IA ({categoria.value}).")


class ILLMPort(Protocol):
    async def gerar_descricao_perfil(
        self,
        estilo_processamento: EstiloProcessamento,
        percepcao: Percepcao,
        entrada: Entrada,
        compreensao: Compreensao,
    ) -> str | None: ...

    async def reescrever_conteudo(
        self,
        conteudo_original: bytes,
        estilo_processamento: EstiloProcessamento,
        percepcao: Percepcao,
        entrada: Entrada,
        compreensao: Compreensao,
    ) -> ConteudoPersonalizado | None: ...
