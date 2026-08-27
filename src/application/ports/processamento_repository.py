from datetime import timedelta
from typing import Protocol
from uuid import UUID

from domain.processamento.processamento import Processamento


class IProcessamentoRepository(Protocol):
    async def adicionar(self, processamento: Processamento) -> None: ...

    async def atualizar(self, processamento: Processamento) -> None: ...

    async def obter_por_id(self, id: UUID) -> Processamento | None: ...

    async def listar_por_aluno_id(
        self, aluno_id: UUID, pagina: int, tamanho_pagina: int
    ) -> tuple[list[Processamento], int]: ...

    async def liberar_presos(self, idade_maxima: timedelta) -> list[UUID]: ...
