from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LogCadastroRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aluno_id: UUID
    processamento_id: UUID | None = None
    acao: str
    descricao: str | None = None


class LogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    aluno_id: UUID
    processamento_id: UUID | None
    acao: str
    descricao: str | None
    timestamp: datetime


class PaginacaoResponse(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class LogListagemResponse(BaseModel):
    data: list[LogResponse]
    pagination: PaginacaoResponse
