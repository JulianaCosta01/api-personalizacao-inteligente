from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from domain.perfil.dimensoes import Compreensao, Entrada, EstiloProcessamento, Percepcao


class PerfilCadastroRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estilo_processamento: EstiloProcessamento
    percepcao: Percepcao
    entrada: Entrada
    compreensao: Compreensao


class PerfilResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    aluno_id: UUID
    estilo_processamento: EstiloProcessamento
    percepcao: Percepcao
    entrada: Entrada
    compreensao: Compreensao
    descricao_llm: str | None
    data_atualizacao: datetime


class PaginacaoResponse(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class PerfilListagemResponse(BaseModel):
    data: list[PerfilResponse]
    pagination: PaginacaoResponse
