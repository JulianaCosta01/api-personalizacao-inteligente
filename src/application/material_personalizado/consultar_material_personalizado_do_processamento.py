import logging
from uuid import UUID

from application.ports.material_personalizado_repository import IMaterialPersonalizadoRepository
from application.ports.processamento_repository import IProcessamentoRepository
from domain.material_personalizado.material_personalizado import MaterialPersonalizado
from domain.processamento.status_processamento import StatusProcessamento
from domain.shared.exceptions import ConflitoDeEstadoError, RecursoNaoEncontradoError

logger = logging.getLogger(__name__)


class ConsultarMaterialPersonalizadoDoProcessamentoUseCase:
    """Documento 3 §4.5 — GET /processamentos/{id}/material."""

    def __init__(
        self,
        processamento_repositorio: IProcessamentoRepository,
        material_personalizado_repositorio: IMaterialPersonalizadoRepository,
    ) -> None:
        self._processamento_repositorio = processamento_repositorio
        self._material_personalizado_repositorio = material_personalizado_repositorio

    async def executar(self, processamento_id: UUID) -> MaterialPersonalizado:
        processamento = await self._processamento_repositorio.obter_por_id(processamento_id)
        if processamento is None:
            raise RecursoNaoEncontradoError(
                code="PROCESSAMENTO_NAO_ENCONTRADO",
                message="Processamento não encontrado.",
                details={"processamento_id": str(processamento_id)},
            )

        if processamento.status != StatusProcessamento.CONCLUIDO:
            # Documento 3 §4.5: o processamento existe, só ainda não gerou o
            # material — 409, não 404, para diferenciar de "id inexistente".
            raise ConflitoDeEstadoError(
                code="MATERIAL_PERSONALIZADO_INDISPONIVEL",
                message="O processamento ainda não foi concluído.",
                details={
                    "processamento_id": str(processamento_id),
                    "status": processamento.status.value,
                },
            )

        material = await self._material_personalizado_repositorio.obter_por_processamento_id(
            processamento_id
        )
        if material is None:
            # Defensivo: o Worker sempre grava o material antes de marcar o
            # processamento como concluido (Documento 3 §12, etapa 18) — chegar
            # aqui indica inconsistência de dados, não ausência documentada.
            logger.warning(
                "Processamento %s está CONCLUIDO mas não possui material "
                "personalizado associado — inconsistência de dados.",
                processamento_id,
            )
            raise ConflitoDeEstadoError(
                code="MATERIAL_PERSONALIZADO_INDISPONIVEL",
                message="O material personalizado ainda não está disponível.",
                details={"processamento_id": str(processamento_id)},
            )

        return material
