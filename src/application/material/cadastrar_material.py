import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from application.ports.material_repository import IMaterialRepository
from application.ports.object_storage import IObjectStoragePort
from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo, eh_pdf_valido
from domain.shared.exceptions import EntradaInvalidaError, RecursoNaoEncontradoError

logger = logging.getLogger(__name__)


@dataclass
class CadastrarMaterialInput:
    titulo: str
    nome_arquivo: str
    conteudo: bytes
    material_original_id: UUID | None = None


class CadastrarMaterialUseCase:
    def __init__(self, repositorio: IMaterialRepository, storage: IObjectStoragePort) -> None:
        self._repositorio = repositorio
        self._storage = storage

    async def executar(self, dados: CadastrarMaterialInput) -> MaterialDidatico:
        if not eh_pdf_valido(dados.conteudo):
            raise EntradaInvalidaError(
                code="ARQUIVO_INVALIDO", message="O arquivo enviado não é um PDF válido."
            )

        material_original = None
        if dados.material_original_id is not None:
            material_original = await self._repositorio.obter_por_id(dados.material_original_id)
            if material_original is None:
                raise RecursoNaoEncontradoError(
                    code="MATERIAL_NAO_ENCONTRADO",
                    message="Material original não encontrado.",
                    details={"material_id": str(dados.material_original_id)},
                )

        # Chave gerada internamente: nunca deriva do nome enviado pelo cliente.
        chave = f"materiais/{uuid4()}.pdf"
        await self._storage.salvar(chave, dados.conteudo, TipoArquivo.PDF)

        try:
            return await self._persistir(material_original, dados, chave)
        except Exception:
            await self._reverter_upload(chave)
            raise

    async def _persistir(
        self,
        material_original: MaterialDidatico | None,
        dados: CadastrarMaterialInput,
        chave: str,
    ) -> MaterialDidatico:
        if material_original is not None:
            material_original.revisar(
                nome_arquivo=dados.nome_arquivo,
                tipo_arquivo=TipoArquivo.PDF,
                caminho_storage=chave,
                data_upload=datetime.now(UTC),
            )
            await self._repositorio.atualizar(material_original)
            return material_original

        material = MaterialDidatico(
            id=uuid4(),
            titulo=dados.titulo,
            nome_arquivo=dados.nome_arquivo,
            tipo_arquivo=TipoArquivo.PDF,
            caminho_storage=chave,
            versao=1,
            data_upload=datetime.now(UTC),
        )
        await self._repositorio.adicionar(material)
        return material

    async def _reverter_upload(self, chave: str) -> None:
        try:
            await self._storage.remover(chave)
        except Exception:
            logger.exception("Falha ao remover objeto órfão do Storage: %s", chave)
