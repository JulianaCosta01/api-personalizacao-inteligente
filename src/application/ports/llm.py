from dataclasses import dataclass
from typing import Protocol

from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao


@dataclass
class ConteudoPersonalizado:
    conteudo_pdf: bytes
    resumo: str


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
