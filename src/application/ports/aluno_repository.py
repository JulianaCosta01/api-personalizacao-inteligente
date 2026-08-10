from typing import Protocol
from uuid import UUID

from domain.aluno.aluno import Aluno


class IAlunoRepository(Protocol):
    async def obter_por_id(self, id: UUID) -> Aluno | None: ...

    async def obter_por_matricula(self, matricula: str) -> Aluno | None: ...

    async def adicionar(self, aluno: Aluno) -> None: ...

    async def atualizar(self, aluno: Aluno) -> None: ...
