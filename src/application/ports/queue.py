from typing import Protocol
from uuid import UUID


class IQueuePort(Protocol):
    async def publicar(self, processamento_id: UUID) -> None: ...

    async def reivindicar_proximo(self) -> UUID | None: ...

    async def remover(self, processamento_id: UUID) -> None: ...
