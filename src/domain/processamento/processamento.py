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
    # Quantas vezes o Worker reivindicou este processamento; limita o reprocessamento de um job
    # que derruba o processo ou nunca termina (ver worker_tentativas_maximas).
    tentativas: int = 0
    # Espera entre tentativas: enquanto estiver no futuro, o Processamento pendente não pode ser
    # reivindicado (ver FilaPostgres.reivindicar_proximo). None = disponível imediatamente.
    disponivel_em: datetime | None = None

    def marcar_como_erro(self, mensagem: str) -> None:
        self.status = StatusProcessamento.ERRO
        self.erro = mensagem
        self.fim = datetime.now(UTC)

    def marcar_como_concluido(self) -> None:
        self.status = StatusProcessamento.CONCLUIDO
        self.fim = datetime.now(UTC)

    def devolver_para_nova_tentativa(self, disponivel_em: datetime) -> None:
        # Falha transitória do provedor: volta para a fila sem encerrar. `fim` e `erro` seguem
        # vazios; `inicio` permanece até a próxima reivindicação, que o renova.
        self.status = StatusProcessamento.PENDENTE
        self.disponivel_em = disponivel_em
