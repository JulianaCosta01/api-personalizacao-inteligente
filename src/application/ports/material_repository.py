from typing import Protocol
from uuid import UUID

from domain.material.material_didatico import MaterialDidatico


class IMaterialRepository(Protocol):
    async def obter_por_id(self, id: UUID) -> MaterialDidatico | None: ...

    async def adicionar(self, material: MaterialDidatico) -> None: ...

    async def atualizar(self, material: MaterialDidatico) -> None: ...

    async def listar(
        self, pagina: int, tamanho_pagina: int, titulo: str | None
    ) -> tuple[list[MaterialDidatico], int]: ...
