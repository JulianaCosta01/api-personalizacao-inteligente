from dataclasses import dataclass
from uuid import UUID

from application.ports.log_repository import ILogRepository
from application.ports.processamento_repository import IProcessamentoRepository
from domain.log.log_interacao import LogInteracao
from domain.shared.exceptions import RecursoNaoEncontradoError


@dataclass
class ListarLogsDoProcessamentoInput:
    processamento_id: UUID
    pagina: int = 1
    tamanho_pagina: int = 20


@dataclass
class ListarLogsDoProcessamentoResultado:
    itens: list[LogInteracao]
    total_itens: int


class ListarLogsDoProcessamentoUseCase:
    def __init__(
        self,
        processamento_repositorio: IProcessamentoRepository,
        log_repositorio: ILogRepository,
    ) -> None:
        self._processamento_repositorio = processamento_repositorio
        self._log_repositorio = log_repositorio

    async def executar(
        self, dados: ListarLogsDoProcessamentoInput
    ) -> ListarLogsDoProcessamentoResultado:
        processamento = await self._processamento_repositorio.obter_por_id(dados.processamento_id)
        if processamento is None:
            raise RecursoNaoEncontradoError(
                code="PROCESSAMENTO_NAO_ENCONTRADO",
                message="Processamento não encontrado.",
                details={"processamento_id": str(dados.processamento_id)},
            )

        itens, total = await self._log_repositorio.listar_por_processamento_id(
            processamento_id=dados.processamento_id,
            pagina=dados.pagina,
            tamanho_pagina=dados.tamanho_pagina,
        )
        return ListarLogsDoProcessamentoResultado(itens=itens, total_itens=total)
