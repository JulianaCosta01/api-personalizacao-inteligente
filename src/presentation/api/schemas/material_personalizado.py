from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MaterialPersonalizadoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    processamento_id: UUID
    titulo: str
    # URL assinada e temporária (Documento 3, §7) — nunca o caminho/chave bruto
    # do Object Storage. Montada no router a partir de IObjectStoragePort,
    # substituindo o valor já presente no domínio (a chave de armazenamento).
    caminho_pdf: str
    resumo: str
    data_geracao: datetime
