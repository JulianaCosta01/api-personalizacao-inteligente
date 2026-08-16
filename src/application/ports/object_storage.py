from typing import Protocol

from domain.material.tipo_arquivo import TipoArquivo


class IObjectStoragePort(Protocol):
    async def salvar(self, chave: str, conteudo: bytes, tipo_arquivo: TipoArquivo) -> None: ...

    async def remover(self, chave: str) -> None: ...
