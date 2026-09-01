import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from application.ports.llm import ILLMPort
from application.ports.material_personalizado_repository import IMaterialPersonalizadoRepository
from application.ports.material_repository import IMaterialRepository
from application.ports.object_storage import IObjectStoragePort
from application.ports.perfil_repository import IPerfilRepository
from application.ports.processamento_repository import IProcessamentoRepository
from domain.material.tipo_arquivo import TipoArquivo
from domain.material_personalizado.material_personalizado import MaterialPersonalizado
from domain.processamento.processamento import Processamento
from domain.shared.exceptions import RecursoNaoEncontradoError

logger = logging.getLogger(__name__)


class ProcessarPersonalizacaoUseCase:
    def __init__(
        self,
        processamento_repositorio: IProcessamentoRepository,
        material_repositorio: IMaterialRepository,
        perfil_repositorio: IPerfilRepository,
        material_personalizado_repositorio: IMaterialPersonalizadoRepository,
        storage: IObjectStoragePort,
        llm: ILLMPort,
    ) -> None:
        self._processamentos = processamento_repositorio
        self._materiais = material_repositorio
        self._perfis = perfil_repositorio
        self._material_personalizados = material_personalizado_repositorio
        self._storage = storage
        self._llm = llm
        # Exposta para o Worker: se uma etapa posterior ao sucesso falhar (ex.:
        # remoção da mensagem da fila), essa é a chave a reverter do Storage.
        self.chave_pdf_gerada: str | None = None

    async def executar(self, processamento_id: UUID) -> Processamento:
        processamento = await self._processamentos.obter_por_id(processamento_id)
        if processamento is None:
            raise RecursoNaoEncontradoError(
                code="PROCESSAMENTO_NAO_ENCONTRADO",
                message="Processamento não encontrado.",
                details={"processamento_id": str(processamento_id)},
            )

        material = await self._materiais.obter_por_id(processamento.material_didatico_id)
        if material is None:
            raise RecursoNaoEncontradoError(
                code="MATERIAL_NAO_ENCONTRADO",
                message="Material didático não encontrado.",
                details={"material_didatico_id": str(processamento.material_didatico_id)},
            )

        # perfil_id é o snapshot gravado na criação do Processamento — não o
        # perfil mais recente do aluno, que pode ter mudado desde então.
        perfil = await self._perfis.obter_por_id(processamento.perfil_id)
        if perfil is None:
            raise RecursoNaoEncontradoError(
                code="PERFIL_NAO_ENCONTRADO",
                message="Perfil de aprendizagem não encontrado.",
                details={"perfil_id": str(processamento.perfil_id)},
            )

        try:
            conteudo_original = await self._storage.obter(material.caminho_storage)
            resultado = await self._llm.reescrever_conteudo(
                conteudo_original,
                perfil.estilo_processamento,
                perfil.percepcao,
                perfil.entrada,
                perfil.compreensao,
            )
            if resultado is None:
                raise RuntimeError("O modelo de linguagem não retornou conteúdo adaptado.")

            chave = f"materiais-personalizados/{uuid4()}.pdf"
            await self._storage.salvar(chave, resultado.conteudo_pdf, TipoArquivo.PDF)
            self.chave_pdf_gerada = chave

            material_personalizado = MaterialPersonalizado(
                id=uuid4(),
                processamento_id=processamento.id,
                titulo=material.titulo,
                caminho_pdf=chave,
                resumo=resultado.resumo,
                data_geracao=datetime.now(UTC),
            )
            try:
                await self._material_personalizados.adicionar(material_personalizado)
            except Exception:
                # O PDF já está no Storage nesse ponto e um rollback do banco não
                # o remove: sem isso ficaria um arquivo órfão sem registro algum.
                await self.reverter_upload(chave)
                raise
        except Exception:
            logger.exception(
                "Falha ao processar a personalização do processamento %s.", processamento.id
            )
            processamento.marcar_como_erro("Falha ao processar a personalização do material.")
            await self._processamentos.atualizar(processamento)
            return processamento

        processamento.marcar_como_concluido()
        await self._processamentos.atualizar(processamento)
        return processamento

    async def reverter_upload(self, chave: str) -> None:
        """Compensa um PDF já enviado ao Storage quando uma etapa posterior falha.

        Também é usada pelo Worker: se a remoção da mensagem da fila falhar
        após o sucesso desta execução, o rollback do banco desfaz o
        MaterialPersonalizado mas não o objeto já gravado no Storage.
        """
        try:
            await self._storage.remover(chave)
        except Exception:
            logger.exception("Falha ao remover PDF personalizado órfão do Storage: %s", chave)
