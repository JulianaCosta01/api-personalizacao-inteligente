from dataclasses import dataclass
from uuid import UUID

from application.ports.aluno_repository import IAlunoRepository
from domain.aluno.aluno import Aluno
from domain.shared.exceptions import RecursoNaoEncontradoError


@dataclass
class AtualizarAlunoInput:
    id: UUID
    nome: str
    email: str


class AtualizarAlunoUseCase:
    def __init__(self, repositorio: IAlunoRepository) -> None:
        self._repositorio = repositorio

    async def executar(self, dados: AtualizarAlunoInput) -> Aluno:
        aluno = await self._repositorio.obter_por_id(dados.id)
        if aluno is None:
            raise RecursoNaoEncontradoError(
                code="ALUNO_NAO_ENCONTRADO",
                message="Aluno não encontrado.",
                details={"aluno_id": str(dados.id)},
            )

        aluno.atualizar_cadastro(nome=dados.nome, email=dados.email)
        await self._repositorio.atualizar(aluno)
        return aluno
