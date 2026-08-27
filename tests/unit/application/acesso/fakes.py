from uuid import UUID

from application.ports.acesso_repository import IAcessoRepository
from domain.acesso.acesso_material_personalizado import AcessoMaterialPersonalizado


class AcessoRepositorioFake(IAcessoRepository):
    def __init__(self, falhar_escrita: bool = False) -> None:
        self._acessos: dict[tuple[UUID, UUID], AcessoMaterialPersonalizado] = {}
        self.falhar_escrita = falhar_escrita

    def semear(self, acesso: AcessoMaterialPersonalizado) -> None:
        self._acessos[(acesso.material_personalizado_id, acesso.aluno_id)] = acesso

    async def adicionar(self, acesso: AcessoMaterialPersonalizado) -> None:
        if self.falhar_escrita:
            raise RuntimeError("falha simulada de banco")
        self._acessos[(acesso.material_personalizado_id, acesso.aluno_id)] = acesso

    async def atualizar(self, acesso: AcessoMaterialPersonalizado) -> None:
        if self.falhar_escrita:
            raise RuntimeError("falha simulada de banco")
        self._acessos[(acesso.material_personalizado_id, acesso.aluno_id)] = acesso

    async def obter_por_material_personalizado_id_e_aluno_id(
        self, material_personalizado_id: UUID, aluno_id: UUID
    ) -> AcessoMaterialPersonalizado | None:
        return self._acessos.get((material_personalizado_id, aluno_id))

    async def obter_por_material_personalizado_id(
        self, material_personalizado_id: UUID
    ) -> AcessoMaterialPersonalizado | None:
        return next(
            (a for (mid, _), a in self._acessos.items() if mid == material_personalizado_id),
            None,
        )
