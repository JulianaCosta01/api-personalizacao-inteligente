import httpx

from application.ports.object_storage import IObjectStoragePort
from domain.material.tipo_arquivo import TipoArquivo


class ErroDeStorage(Exception):
    pass


def _validar_chave(chave: str) -> None:
    # Cobre traversal Unix/Windows (.., /, \) e bytes nulos, que alguns
    # filesystems usam para truncar a string e contornar checagem de extensão.
    if ".." in chave or chave.startswith("/") or "\\" in chave or "\x00" in chave:
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

    async def obter(self, chave: str) -> bytes:
        _validar_chave(chave)
        resposta = await self._cliente.get(f"/object/{self._bucket}/{chave}")
        if resposta.status_code >= 400:
            raise ErroDeStorage(f"Falha ao ler objeto do Storage (status {resposta.status_code}).")
        return resposta.content

    async def criar_url_leitura(self, chave: str, expiracao_segundos: int) -> str:
        # API do Supabase Storage devolve {"signedURL": "/object/sign/.../token=..."}, um
        # path relativo; o cliente HTTP já tem essa raiz como base_url (storage/cliente.py).
        _validar_chave(chave)
        resposta = await self._cliente.post(
            f"/object/sign/{self._bucket}/{chave}",
            json={"expiresIn": expiracao_segundos},
        )
        if resposta.status_code >= 400:
            raise ErroDeStorage(
                f"Falha ao gerar URL assinada no Storage (status {resposta.status_code})."
            )
        caminho_assinado = resposta.json()["signedURL"]
        return f"{str(self._cliente.base_url).rstrip('/')}{caminho_assinado}"
