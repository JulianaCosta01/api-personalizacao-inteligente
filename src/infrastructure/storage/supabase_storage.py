import httpx

from application.ports.object_storage import IObjectStoragePort
from domain.material.tipo_arquivo import TipoArquivo


class ErroDeStorage(Exception):
    pass


def _validar_chave(chave: str) -> None:
    # ".." e "/" absoluto cobrem traversal estilo Unix; "\\" cobre separador
    # Windows (tanto "..\\" quanto caminhos absolutos como "C:\\..."); bytes
    # nulos são rejeitados porque algumas APIs/filesystems truncam a string
    # no primeiro \x00, permitindo contornar uma checagem de extensão feita
    # antes deste ponto. Chaves geradas pelo próprio sistema (UUID) nunca
    # contêm nenhum desses caracteres, então nada muda para o uso legítimo.
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
        # API do Supabase Storage: POST /object/sign/{bucket}/{chave} devolve
        # {"signedURL": "/object/sign/{bucket}/{chave}?token=..."} — um path
        # relativo à raiz do Storage, não uma URL completa. O cliente HTTP usado
        # aqui já tem essa raiz como base_url (ver infrastructure/storage/cliente.py),
        # então a URL final é essa base + o path devolvido, sem barra duplicada.
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
