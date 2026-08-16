from typing import Protocol
from uuid import UUID

from domain.perfil.perfil import Perfil


class IPerfilRepository(Protocol):
    async def adicionar(self, perfil: Perfil) -> None: ...

    async def atualizar(self, perfil: Perfil) -> None: ...

    async def obter_mais_recente_por_aluno_id(self, aluno_id: UUID) -> Perfil | None: ...

    async def listar_por_aluno_id(
        self, aluno_id: UUID, pagina: int, tamanho_pagina: int
    ) -> tuple[list[Perfil], int]: ...
