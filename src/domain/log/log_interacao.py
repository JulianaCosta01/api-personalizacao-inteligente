from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class LogInteracao:
    """Registro de auditoria/pesquisa de um evento do fluxo do aluno.

    Imutável: nenhuma regra de negócio altera um log já registrado.
    """

    id: UUID
    aluno_id: UUID
    processamento_id: UUID | None
    acao: str
    descricao: str | None
    timestamp: datetime
