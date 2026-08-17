from datetime import UTC, datetime, timedelta
from uuid import UUID

from application.ports.material_personalizado_repository import IMaterialPersonalizadoRepository
from application.ports.processamento_repository import IProcessamentoRepository
from application.ports.queue import IQueuePort
from domain.material_personalizado.material_personalizado import MaterialPersonalizado
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento


class ProcessamentoRepositorioFake(IProcessamentoRepository):
    def __init__(self) -> None:
        self._processamentos: dict[UUID, Processamento] = {}

    def semear(self, processamento: Processamento) -> None:
        self._processamentos[processamento.id] = processamento

    async def adicionar(self, processamento: Processamento) -> None:
        self._processamentos[processamento.id] = processamento

    async def atualizar(self, processamento: Processamento) -> None:
        self._processamentos[processamento.id] = processamento

    async def obter_por_id(self, id: UUID) -> Processamento | None:
        return self._processamentos.get(id)

    async def listar_por_aluno_id(
        self, aluno_id: UUID, pagina: int, tamanho_pagina: int
    ) -> tuple[list[Processamento], int]:
        do_aluno = sorted(
            (p for p in self._processamentos.values() if p.aluno_id == aluno_id),
            key=lambda p: p.data_criacao,
            reverse=True,
        )
        inicio = (pagina - 1) * tamanho_pagina
        return do_aluno[inicio : inicio + tamanho_pagina], len(do_aluno)

    async def liberar_presos(self, idade_maxima: timedelta) -> list[UUID]:
        limite = datetime.now(UTC) - idade_maxima
        liberados = []
        for processamento in self._processamentos.values():
            if (
                processamento.status == StatusProcessamento.EM_PROCESSAMENTO
                and processamento.inicio is not None
                and processamento.inicio < limite
            ):
                processamento.status = StatusProcessamento.PENDENTE
                liberados.append(processamento.id)
        return liberados


class QueueFake(IQueuePort):
    def __init__(self, levantar: bool = False, levantar_reivindicacao: bool = False) -> None:
        self.levantar = levantar
        self.levantar_reivindicacao = levantar_reivindicacao
        self.publicados: list[UUID] = []
        self.fila: list[UUID] = []
        self.removidos: list[UUID] = []

    async def publicar(self, processamento_id: UUID) -> None:
        if self.levantar:
            raise RuntimeError("falha simulada da fila")
        self.publicados.append(processamento_id)
        self.fila.append(processamento_id)

    async def reivindicar_proximo(self) -> UUID | None:
        if self.levantar_reivindicacao:
            raise RuntimeError("falha simulada ao reivindicar")
        if not self.fila:
            return None
        return self.fila.pop(0)

    async def remover(self, processamento_id: UUID) -> None:
        self.removidos.append(processamento_id)


class MaterialPersonalizadoRepositorioFake(IMaterialPersonalizadoRepository):
    def __init__(self, falhar_escrita: bool = False) -> None:
        self.falhar_escrita = falhar_escrita
        self.adicionados: list[MaterialPersonalizado] = []

    async def adicionar(self, material_personalizado: MaterialPersonalizado) -> None:
        if self.falhar_escrita:
            raise RuntimeError("falha simulada de banco")
        self.adicionados.append(material_personalizado)
