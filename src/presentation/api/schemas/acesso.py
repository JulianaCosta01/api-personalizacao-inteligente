from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from domain.acesso.status_leitura import StatusLeitura

# Documento 3 §4.7: porcentagem_leitura é uma fração entre 0 e 1, não um
# percentual entre 0 e 100 (ex.: 0.78 = 78% lido). A coluna correspondente
# é Numeric(5, 4), que só comporta esse intervalo — sem o ge/le abaixo, um
# cliente que envie um percentual "cru" (ex.: 25.0) derruba a requisição
# com um erro de overflow do banco em vez de um 400 claro.
PorcentagemLeitura = Annotated[
    float,
    Field(
        ge=0,
        le=1,
        description=(
            "Fração de leitura do material, entre 0 e 1 (ex.: 0.78 representa 78% lido). "
            "Documento 3 §4.7."
        ),
        examples=[0.78],
    ),
]


class AcessoAtualizacaoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aluno_id: UUID
    tempo_leitura_incremento_segundos: int
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
