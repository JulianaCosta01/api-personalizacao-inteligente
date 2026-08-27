from dataclasses import dataclass

from application.ports.material_repository import IMaterialRepository
from domain.material.material_didatico import MaterialDidatico


@dataclass
class ListarMateriaisInput:
    pagina: int = 1
    tamanho_pagina: int = 20
    titulo: str | None = None


@dataclass
class ListarMateriaisResultado:
    itens: list[MaterialDidatico]
    total_itens: int


class ListarMateriaisUseCase:
    def __init__(self, repositorio: IMaterialRepository) -> None:
        self._repositorio = repositorio

    async def executar(self, dados: ListarMateriaisInput) -> ListarMateriaisResultado:
        itens, total = await self._repositorio.listar(
            pagina=dados.pagina, tamanho_pagina=dados.tamanho_pagina, titulo=dados.titulo
        )
        return ListarMateriaisResultado(itens=itens, total_itens=total)
