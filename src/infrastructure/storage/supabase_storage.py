import httpx

from application.ports.object_storage import IObjectStoragePort
from domain.material.tipo_arquivo import TipoArquivo


class ErroDeStorage(Exception):
    pass


def _validar_chave(chave: str) -> None:
    if ".." in chave or chave.startswith("/"):
        raise ErroDeStorage("Chave de objeto inválida.")


class SupabaseStorageAdapter(IObjectStoragePort):
    def __init__(self, cliente: httpx.AsyncClient, bucket: str) -> None:
        self._cliente = cliente
        self._bucket = bucket

    async def salvar(self, chave: str, conteudo: bytes, tipo_arquivo: TipoArquivo) -> None:
        _validar_chave(chave)
        resposta = await self._cliente.post(
            f"/object/{self._bucket}/{chave}",
            content=conteudo,
            headers={"Content-Type": tipo_arquivo.value},
        )
        if resposta.status_code >= 400:
            raise ErroDeStorage(
                f"Falha ao gravar objeto no Storage (status {resposta.status_code})."
            )

    async def remover(self, chave: str) -> None:
        _validar_chave(chave)
        resposta = await self._cliente.delete(f"/object/{self._bucket}/{chave}")
        if resposta.status_code >= 400:
            raise ErroDeStorage(
                f"Falha ao remover objeto do Storage (status {resposta.status_code})."
            )
