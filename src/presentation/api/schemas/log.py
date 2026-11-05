from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LogCadastroRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aluno_id: UUID
    processamento_id: UUID | None = None
    # acao: coluna de 100 caracteres. descricao: texto livre, limitado para não crescer sem teto.
    acao: str = Field(min_length=1, max_length=100)
    descricao: str | None = Field(default=None, max_length=2000)


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
