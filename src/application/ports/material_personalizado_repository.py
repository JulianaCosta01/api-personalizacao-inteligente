from typing import Protocol
from uuid import UUID

from domain.material_personalizado.material_personalizado import MaterialPersonalizado


class IMaterialPersonalizadoRepository(Protocol):
    async def adicionar(self, material_personalizado: MaterialPersonalizado) -> None: ...

    async def obter_por_id(self, id: UUID) -> MaterialPersonalizado | None: ...

    async def obter_por_processamento_id(
        self, processamento_id: UUID
    ) -> MaterialPersonalizado | None: ...
