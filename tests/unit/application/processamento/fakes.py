from datetime import UTC, datetime, timedelta
from uuid import UUID

from application.ports.material_personalizado_repository import IMaterialPersonalizadoRepository
from application.ports.processamento_repository import IProcessamentoRepository
from application.ports.queue import IQueuePort
from domain.material_personalizado.material_personalizado import MaterialPersonalizado
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento


class ProcessamentoRepositorioFake(IProcessamentoRepository):
    def __init__(self, perder_posse: bool = False) -> None:
        self._processamentos: dict[UUID, Processamento] = {}
        # Simula a perda de posse: atualizar_se_dono não grava e devolve False.
        self.perder_posse = perder_posse
        # Registro das devolvidas à fila: (id, disponivel_em, tentativas_maximas).
        self.devolvidos: list[tuple[UUID, datetime, int]] = []

    def semear(self, processamento: Processamento) -> None:
        self._processamentos[processamento.id] = processamento

    async def adicionar(self, processamento: Processamento) -> None:
        self._processamentos[processamento.id] = processamento

    async def atualizar(self, processamento: Processamento) -> None:
        self._processamentos[processamento.id] = processamento

    async def atualizar_se_dono(self, processamento: Processamento) -> bool:
        if self.perder_posse:
            return False
        self._processamentos[processamento.id] = processamento
        return True

    async def devolver_para_fila_se_dono(
        self, processamento: Processamento, disponivel_em: datetime, tentativas_maximas: int
    ) -> bool:
        # Mesma condição do SQL real: posse (aqui simulada) e tentativas abaixo do limite.
        if self.perder_posse or processamento.tentativas >= tentativas_maximas:
            return False
        self.devolvidos.append((processamento.id, disponivel_em, tentativas_maximas))
        self._processamentos[processamento.id] = processamento
        return True

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

    async def liberar_presos(
        self, idade_maxima: timedelta, tentativas_maximas: int | None = None
    ) -> list[UUID]:
        limite = datetime.now(UTC) - idade_maxima
        liberados = []
        for processamento in self._processamentos.values():
            if (
                processamento.status == StatusProcessamento.EM_PROCESSAMENTO
                and processamento.inicio is not None
                and processamento.inicio < limite
                and (tentativas_maximas is None or processamento.tentativas < tentativas_maximas)
            ):
                processamento.status = StatusProcessamento.PENDENTE
                liberados.append(processamento.id)
        return liberados

    async def esgotar_tentativas_dos_presos(
        self, idade_maxima: timedelta, tentativas_maximas: int
    ) -> list[UUID]:
        limite = datetime.now(UTC) - idade_maxima
        esgotados = []
        for processamento in self._processamentos.values():
            if (
                processamento.status == StatusProcessamento.EM_PROCESSAMENTO
                and processamento.inicio is not None
                and processamento.inicio < limite
                and processamento.tentativas >= tentativas_maximas
            ):
                processamento.marcar_como_erro("Número máximo de tentativas excedido.")
                esgotados.append(processamento.id)
        return esgotados


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

    async def obter_por_id(self, id: UUID) -> MaterialPersonalizado | None:
        return next((m for m in self.adicionados if m.id == id), None)

    async def obter_por_processamento_id(
        self, processamento_id: UUID
    ) -> MaterialPersonalizado | None:
        return next((m for m in self.adicionados if m.processamento_id == processamento_id), None)
