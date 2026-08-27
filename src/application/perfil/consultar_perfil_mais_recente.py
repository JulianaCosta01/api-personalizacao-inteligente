from uuid import UUID

from application.ports.aluno_repository import IAlunoRepository
from application.ports.perfil_repository import IPerfilRepository
from domain.perfil.perfil import Perfil
from domain.shared.exceptions import RecursoNaoEncontradoError


class ConsultarPerfilMaisRecenteUseCase:
    def __init__(
        self, aluno_repositorio: IAlunoRepository, perfil_repositorio: IPerfilRepository
    ) -> None:
        self._aluno_repositorio = aluno_repositorio
        self._perfil_repositorio = perfil_repositorio

    async def executar(self, aluno_id: UUID) -> Perfil:
        aluno = await self._aluno_repositorio.obter_por_id(aluno_id)
        if aluno is None:
            raise RecursoNaoEncontradoError(
                code="ALUNO_NAO_ENCONTRADO",
                message="Aluno não encontrado.",
                details={"aluno_id": str(aluno_id)},
            )

        perfil = await self._perfil_repositorio.obter_mais_recente_por_aluno_id(aluno_id)
        if perfil is None:
            raise RecursoNaoEncontradoError(
                code="PERFIL_NAO_ENCONTRADO",
                message="O aluno ainda não possui perfil de aprendizagem cadastrado.",
                details={"aluno_id": str(aluno_id)},
            )
        return perfil
