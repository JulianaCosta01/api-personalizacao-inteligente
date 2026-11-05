from uuid import UUID

from application.ports.aluno_repository import IAlunoRepository
from domain.aluno.aluno import Aluno


class AlunoRepositorioFake(IAlunoRepository):
    """Dublê em memória, sem banco"""

    def __init__(self) -> None:
        self._alunos: dict[UUID, Aluno] = {}

    async def obter_por_id(self, id: UUID) -> Aluno | None:
        return self._alunos.get(id)

    async def obter_por_matricula(self, matricula: str) -> Aluno | None:
        return next((a for a in self._alunos.values() if a.matricula == matricula), None)

    async def adicionar(self, aluno: Aluno) -> None:
        self._alunos[aluno.id] = aluno

    async def atualizar(self, aluno: Aluno) -> None:
        self._alunos[aluno.id] = aluno
