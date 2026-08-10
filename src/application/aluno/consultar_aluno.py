from uuid import UUID

from application.ports.aluno_repository import IAlunoRepository
from domain.aluno.aluno import Aluno
from domain.shared.exceptions import RecursoNaoEncontradoError


class ConsultarAlunoUseCase:
    def __init__(self, repositorio: IAlunoRepository) -> None:
        self._repositorio = repositorio

    async def executar(self, id: UUID) -> Aluno:
        aluno = await self._repositorio.obter_por_id(id)
        if aluno is None:
            raise RecursoNaoEncontradoError(
                code="ALUNO_NAO_ENCONTRADO",
                message="Aluno não encontrado.",
                details={"aluno_id": str(id)},
            )
        return aluno
