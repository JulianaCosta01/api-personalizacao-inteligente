from typing import Protocol
from uuid import UUID

from domain.log.log_interacao import LogInteracao


class ILogRepository(Protocol):
    async def adicionar(self, log: LogInteracao) -> None: ...

    async def listar_por_processamento_id(
        self, processamento_id: UUID, pagina: int, tamanho_pagina: int
    ) -> tuple[list[LogInteracao], int]: ...
