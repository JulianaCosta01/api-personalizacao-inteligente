from uuid import UUID

from application.ports.material_personalizado_repository import IMaterialPersonalizadoRepository
from domain.material_personalizado.material_personalizado import MaterialPersonalizado
from domain.shared.exceptions import RecursoNaoEncontradoError


class ConsultarMaterialPersonalizadoUseCase:
    """GET /materiais-personalizados/{id}: consulta direta pelo id do material
    personalizado, sem passar pelo processamento de origem."""

    def __init__(
        self, material_personalizado_repositorio: IMaterialPersonalizadoRepository
    ) -> None:
        self._material_personalizado_repositorio = material_personalizado_repositorio

    async def executar(self, id: UUID) -> MaterialPersonalizado:
        material = await self._material_personalizado_repositorio.obter_por_id(id)
        if material is None:
            raise RecursoNaoEncontradoError(
                code="MATERIAL_PERSONALIZADO_NAO_ENCONTRADO",
                message="Material personalizado não encontrado.",
                details={"id": str(id)},
            )
        return material
