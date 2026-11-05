from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from domain.processamento.processamento import Processamento


class IProcessamentoRepository(Protocol):
    async def adicionar(self, processamento: Processamento) -> None: ...

    async def atualizar(self, processamento: Processamento) -> None: ...

    async def obter_por_id(self, id: UUID) -> Processamento | None: ...

    async def listar_por_aluno_id(
        self, aluno_id: UUID, pagina: int, tamanho_pagina: int
    ) -> tuple[list[Processamento], int]: ...

    async def atualizar_se_dono(self, processamento: Processamento) -> bool:
        """Grava o resultado do Worker só se ele ainda for o dono da execução.

        Dono = a linha continua em_processamento com o mesmo `inicio` (a reivindicação) que o
        objeto carrega. Devolve False, sem gravar nada, se a posse foi perdida (recuperação,
        outra reivindicação ou conclusão por outra execução).
        """
        ...

    async def devolver_para_fila_se_dono(
        self, processamento: Processamento, disponivel_em: datetime, tentativas_maximas: int
    ) -> bool:
        """Devolve o Processamento a `pendente`, com espera, só se o Worker ainda for o dono.

        Atômico e condicional: exige `em_processamento`, o mesmo `inicio` (a reivindicação) e
        `tentativas < tentativas_maximas`. Devolve False, sem gravar nada, se a posse foi perdida
        ou se as tentativas se esgotaram; nesse caso quem chamou deve encerrar em erro.
        """
        ...

    async def liberar_presos(
        self, idade_maxima: timedelta, tentativas_maximas: int | None = None
    ) -> list[UUID]: ...

    async def esgotar_tentativas_dos_presos(
        self, idade_maxima: timedelta, tentativas_maximas: int
    ) -> list[UUID]: ...
