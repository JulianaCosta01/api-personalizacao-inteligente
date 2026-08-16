from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from domain.material.tipo_arquivo import TipoArquivo


class MaterialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    titulo: str
    nome_arquivo: str
    tipo_arquivo: TipoArquivo
    versao: int
    data_upload: datetime


class PaginacaoResponse(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class MaterialListagemResponse(BaseModel):
    data: list[MaterialResponse]
    pagination: PaginacaoResponse
