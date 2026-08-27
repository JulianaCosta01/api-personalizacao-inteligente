from dataclasses import dataclass
from uuid import UUID

from application.ports.aluno_repository import IAlunoRepository
from application.ports.perfil_repository import IPerfilRepository
from domain.perfil.perfil import Perfil
from domain.shared.exceptions import RecursoNaoEncontradoError


@dataclass
class ListarPerfisInput:
    aluno_id: UUID
    pagina: int = 1
    tamanho_pagina: int = 20


@dataclass
class ListarPerfisResultado:
    itens: list[Perfil]
    total_itens: int


class ListarPerfisUseCase:
    def __init__(
        self, aluno_repositorio: IAlunoRepository, perfil_repositorio: IPerfilRepository
    ) -> None:
        self._aluno_repositorio = aluno_repositorio
        self._perfil_repositorio = perfil_repositorio

    async def executar(self, dados: ListarPerfisInput) -> ListarPerfisResultado:
        aluno = await self._aluno_repositorio.obter_por_id(dados.aluno_id)
        if aluno is None:
            raise RecursoNaoEncontradoError(
                code="ALUNO_NAO_ENCONTRADO",
                message="Aluno não encontrado.",
                details={"aluno_id": str(dados.aluno_id)},
            )

        itens, total = await self._perfil_repositorio.listar_por_aluno_id(
            aluno_id=dados.aluno_id, pagina=dados.pagina, tamanho_pagina=dados.tamanho_pagina
        )
        return ListarPerfisResultado(itens=itens, total_itens=total)
