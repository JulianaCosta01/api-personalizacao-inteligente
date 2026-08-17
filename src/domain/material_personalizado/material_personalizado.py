from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class MaterialPersonalizado:
    id: UUID
    processamento_id: UUID
    titulo: str
    caminho_pdf: str
    resumo: str
    data_geracao: datetime
