from dataclasses import dataclass
from uuid import UUID

from application.ports.aluno_repository import IAlunoRepository
from application.ports.processamento_repository import IProcessamentoRepository
from domain.processamento.processamento import Processamento
from domain.shared.exceptions import RecursoNaoEncontradoError


@dataclass
class ListarProcessamentosInput:
    aluno_id: UUID
    pagina: int = 1
    tamanho_pagina: int = 20


@dataclass
class ListarProcessamentosResultado:
    itens: list[Processamento]
    total_itens: int


class ListarProcessamentosDoAlunoUseCase:
    def __init__(
        self,
        aluno_repositorio: IAlunoRepository,
        processamento_repositorio: IProcessamentoRepository,
    ) -> None:
        self._aluno_repositorio = aluno_repositorio
        self._processamento_repositorio = processamento_repositorio

    async def executar(self, dados: ListarProcessamentosInput) -> ListarProcessamentosResultado:
        aluno = await self._aluno_repositorio.obter_por_id(dados.aluno_id)
        if aluno is None:
            raise RecursoNaoEncontradoError(
                code="ALUNO_NAO_ENCONTRADO",
                message="Aluno não encontrado.",
                details={"aluno_id": str(dados.aluno_id)},
            )

        itens, total = await self._processamento_repositorio.listar_por_aluno_id(
            aluno_id=dados.aluno_id, pagina=dados.pagina, tamanho_pagina=dados.tamanho_pagina
        )
        return ListarProcessamentosResultado(itens=itens, total_itens=total)
