from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao


@dataclass
class Perfil:
    id: UUID
    aluno_id: UUID
    estilo_processamento: EstiloProcessamento
    percepcao: Percepcao
    entrada: Entrada
    compreensao: Compreensao
    descricao_llm: str | None
    data_atualizacao: datetime
