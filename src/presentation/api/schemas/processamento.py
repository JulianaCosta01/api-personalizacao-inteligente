from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from domain.processamento.status_processamento import StatusProcessamento


class ProcessamentoCadastroRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aluno_id: UUID
    material_didatico_id: UUID


class ProcessamentoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class PaginacaoResponse(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class ProcessamentoListagemResponse(BaseModel):
    data: list[ProcessamentoResponse]
    pagination: PaginacaoResponse
