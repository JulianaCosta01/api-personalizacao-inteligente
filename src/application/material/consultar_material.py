from uuid import UUID

from application.ports.material_repository import IMaterialRepository
from domain.material.material_didatico import MaterialDidatico
from domain.shared.exceptions import RecursoNaoEncontradoError


class ConsultarMaterialUseCase:
    def __init__(self, repositorio: IMaterialRepository) -> None:
        self._repositorio = repositorio

    async def executar(self, id: UUID) -> MaterialDidatico:
        material = await self._repositorio.obter_por_id(id)
        if material is None:
            raise RecursoNaoEncontradoError(
                code="MATERIAL_NAO_ENCONTRADO",
                message="Material não encontrado.",
                details={"material_id": str(id)},
            )
        return material
