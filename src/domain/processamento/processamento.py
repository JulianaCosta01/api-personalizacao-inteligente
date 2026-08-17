from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from domain.processamento.status_processamento import StatusProcessamento


@dataclass
class Processamento:
    id: UUID
    aluno_id: UUID
    material_didatico_id: UUID
    perfil_id: UUID
    status: StatusProcessamento
    modelo_ia: str | None
    data_criacao: datetime
    inicio: datetime | None
    fim: datetime | None
    erro: str | None

    def marcar_como_erro(self, mensagem: str) -> None:
        self.status = StatusProcessamento.ERRO
        self.erro = mensagem
        self.fim = datetime.now(UTC)

    def marcar_como_concluido(self) -> None:
        self.status = StatusProcessamento.CONCLUIDO
        self.fim = datetime.now(UTC)
