from uuid import UUID

from application.ports.log_repository import ILogRepository
from domain.log.log_interacao import LogInteracao


class LogRepositorioFake(ILogRepository):
    def __init__(self, falhar_escrita: bool = False) -> None:
        self._logs: list[LogInteracao] = []
        self.falhar_escrita = falhar_escrita

    def semear(self, log: LogInteracao) -> None:
        self._logs.append(log)

    async def adicionar(self, log: LogInteracao) -> None:
        if self.falhar_escrita:
            raise RuntimeError("falha simulada de banco")
        self._logs.append(log)

    async def listar_por_processamento_id(
        self, processamento_id: UUID, pagina: int, tamanho_pagina: int
    ) -> tuple[list[LogInteracao], int]:
        do_processamento = sorted(
            (log for log in self._logs if log.processamento_id == processamento_id),
            key=lambda log: log.timestamp,
        )
        inicio = (pagina - 1) * tamanho_pagina
        return do_processamento[inicio : inicio + tamanho_pagina], len(do_processamento)
