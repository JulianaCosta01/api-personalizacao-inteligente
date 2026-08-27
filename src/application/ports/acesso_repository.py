from typing import Protocol
from uuid import UUID

from domain.acesso.acesso_material_personalizado import AcessoMaterialPersonalizado


class IAcessoRepository(Protocol):
    async def adicionar(self, acesso: AcessoMaterialPersonalizado) -> None: ...

    async def atualizar(self, acesso: AcessoMaterialPersonalizado) -> None: ...

    async def obter_por_material_personalizado_id_e_aluno_id(
        self, material_personalizado_id: UUID, aluno_id: UUID
    ) -> AcessoMaterialPersonalizado | None: ...

    async def obter_por_material_personalizado_id(
        self, material_personalizado_id: UUID
    ) -> AcessoMaterialPersonalizado | None: ...
