from uuid import UUID

from application.ports.processamento_repository import IProcessamentoRepository
from domain.processamento.processamento import Processamento
from domain.shared.exceptions import RecursoNaoEncontradoError


class ConsultarProcessamentoUseCase:
    def __init__(self, processamento_repositorio: IProcessamentoRepository) -> None:
        self._processamento_repositorio = processamento_repositorio

    async def executar(self, id: UUID) -> Processamento:
        processamento = await self._processamento_repositorio.obter_por_id(id)
        if processamento is None:
            raise RecursoNaoEncontradoError(
                code="PROCESSAMENTO_NAO_ENCONTRADO",
                message="Processamento não encontrado.",
                details={"id": str(id)},
            )
        return processamento
