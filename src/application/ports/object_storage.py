from typing import Protocol

from domain.material.tipo_arquivo import TipoArquivo


class IObjectStoragePort(Protocol):
    async def salvar(self, chave: str, conteudo: bytes, tipo_arquivo: TipoArquivo) -> None: ...

    async def remover(self, chave: str) -> None: ...

    async def obter(self, chave: str) -> bytes: ...

    async def criar_url_leitura(self, chave: str, expiracao_segundos: int) -> str:
        """URL assinada e temporária para leitura direta pelo cliente (Documento 4:
        "obter URL assinada de leitura"). Nunca expõe a chave/caminho bruto do
        Storage — quem decide por quanto tempo a URL é válida é o chamador."""
        ...
