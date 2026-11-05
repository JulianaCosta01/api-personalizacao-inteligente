from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from domain.material.tipo_arquivo import TipoArquivo


@dataclass
class MaterialDidatico:
    id: UUID
    titulo: str
    nome_arquivo: str
    tipo_arquivo: TipoArquivo
    caminho_storage: str
    versao: int
    data_upload: datetime

    def revisar(
        self,
        nome_arquivo: str,
        tipo_arquivo: TipoArquivo,
        caminho_storage: str,
        data_upload: datetime,
    ) -> None:
        # id e titulo identificam o material entre revisões; só arquivo e versão
        # mudam, para que Processamentos já vinculados continuem apontando pra cá.
        self.nome_arquivo = nome_arquivo
        self.tipo_arquivo = tipo_arquivo
        self.caminho_storage = caminho_storage
        self.data_upload = data_upload
        self.versao += 1
