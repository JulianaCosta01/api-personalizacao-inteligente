from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class LogInteracao:
    """Registro de auditoria/pesquisa de um evento do fluxo do aluno (Documento 3 §4.6
    e §10). Imutável após a criação — não há regra de negócio que altere um log já
    registrado, então a entidade não expõe métodos de mutação."""

    id: UUID
    aluno_id: UUID
    processamento_id: UUID | None
    acao: str
    descricao: str | None
    timestamp: datetime
