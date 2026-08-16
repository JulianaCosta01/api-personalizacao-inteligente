from typing import Protocol

from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao


class ILLMPort(Protocol):
    async def gerar_descricao_perfil(
        self,
        estilo_processamento: EstiloProcessamento,
        percepcao: Percepcao,
        entrada: Entrada,
        compreensao: Compreensao,
    ) -> str | None: ...
