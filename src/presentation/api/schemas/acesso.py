from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from domain.acesso.status_leitura import StatusLeitura

# Fração entre 0 e 1, não percentual (0.78 = 78% lido). A coluna é Numeric(5, 4);
# sem o ge/le, um valor "cru" (ex.: 25.0) vira overflow do banco em vez de um 400 claro.
PorcentagemLeitura = Annotated[
    float,
    Field(
        ge=0,
        le=1,
        description="Fração de leitura do material, entre 0 e 1 (ex.: 0.78 representa 78% lido).",
        examples=[0.78],
    ),
]


class AcessoAtualizacaoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aluno_id: UUID
    # Incremento de uma chamada: nunca negativo (reduziria o total) e no máximo 24 h.
    tempo_leitura_incremento_segundos: int = Field(ge=0, le=86_400)
    porcentagem_leitura: PorcentagemLeitura
    download_realizado: bool


class AcessoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    material_personalizado_id: UUID
    aluno_id: UUID
    data_primeiro_acesso: datetime
    data_ultimo_acesso: datetime
    tempo_total_leitura: int
    quantidade_acessos: int
    porcentagem_leitura: float
    download_realizado: bool
    status_leitura: StatusLeitura
