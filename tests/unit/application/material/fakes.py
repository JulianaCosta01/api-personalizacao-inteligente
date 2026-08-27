from uuid import UUID

from application.ports.material_repository import IMaterialRepository
from application.ports.object_storage import IObjectStoragePort
from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo


class MaterialRepositorioFake(IMaterialRepository):
    def __init__(self, falhar_escrita: bool = False) -> None:
        self._materiais: dict[UUID, MaterialDidatico] = {}
        self.falhar_escrita = falhar_escrita

    def semear(self, material: MaterialDidatico) -> None:
        self._materiais[material.id] = material

    async def obter_por_id(self, id: UUID) -> MaterialDidatico | None:
        return self._materiais.get(id)

    async def adicionar(self, material: MaterialDidatico) -> None:
        if self.falhar_escrita:
            raise RuntimeError("falha simulada de banco")
        self._materiais[material.id] = material

    async def atualizar(self, material: MaterialDidatico) -> None:
        if self.falhar_escrita:
            raise RuntimeError("falha simulada de banco")
        self._materiais[material.id] = material

    async def listar(
        self, pagina: int, tamanho_pagina: int, titulo: str | None
    ) -> tuple[list[MaterialDidatico], int]:
        itens = list(self._materiais.values())
        if titulo:
            itens = [m for m in itens if titulo.lower() in m.titulo.lower()]
        inicio = (pagina - 1) * tamanho_pagina
        return itens[inicio : inicio + tamanho_pagina], len(itens)


class ObjectStorageFake(IObjectStoragePort):
    def __init__(
        self,
        falhar_remocao: bool = False,
        falhar_leitura: bool = False,
        falhar_escrita: bool = False,
    ) -> None:
        self.salvos: dict[str, bytes] = {}
        self.removidos: list[str] = []
        self.falhar_remocao = falhar_remocao
        self.falhar_leitura = falhar_leitura
        self.falhar_escrita = falhar_escrita

    async def salvar(self, chave: str, conteudo: bytes, tipo_arquivo: TipoArquivo) -> None:
        if self.falhar_escrita:
            raise RuntimeError("falha simulada ao salvar")
        self.salvos[chave] = conteudo

    async def remover(self, chave: str) -> None:
        if self.falhar_remocao:
            raise RuntimeError("falha simulada ao remover")
        self.removidos.append(chave)
        self.salvos.pop(chave, None)

    async def obter(self, chave: str) -> bytes:
        if self.falhar_leitura:
            raise RuntimeError("falha simulada ao ler")
        conteudo = self.salvos.get(chave)
        if conteudo is None:
            raise RuntimeError(f"objeto inexistente no storage fake: {chave}")
        return conteudo

    async def criar_url_leitura(self, chave: str, expiracao_segundos: int) -> str:
        if self.falhar_leitura:
            raise RuntimeError("falha simulada ao ler")
        if chave not in self.salvos:
            raise RuntimeError(f"objeto inexistente no storage fake: {chave}")
        return f"https://storage.fake/{chave}?expira_em={expiracao_segundos}"
