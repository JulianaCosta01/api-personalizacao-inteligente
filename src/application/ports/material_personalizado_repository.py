from typing import Protocol

from domain.material_personalizado.material_personalizado import MaterialPersonalizado


class IMaterialPersonalizadoRepository(Protocol):
    async def adicionar(self, material_personalizado: MaterialPersonalizado) -> None: ...
