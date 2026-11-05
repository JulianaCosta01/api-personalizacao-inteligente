from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MaterialPersonalizadoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    processamento_id: UUID
    titulo: str
    # URL assinada e temporária, nunca o caminho/chave bruto do Object
    # Storage: montada no router a partir de IObjectStoragePort, substituindo a chave do domínio.
    caminho_pdf: str
    resumo: str
    data_geracao: datetime
