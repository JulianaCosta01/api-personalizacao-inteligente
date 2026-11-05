import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from application.ports.llm import FalhaTransitoriaDoProvedorError, ILLMPort
from application.ports.material_personalizado_repository import IMaterialPersonalizadoRepository
from application.ports.material_repository import IMaterialRepository
from application.ports.object_storage import IObjectStoragePort
from application.ports.perfil_repository import IPerfilRepository
from application.ports.processamento_repository import IProcessamentoRepository
from application.processamento.politica_de_repeticao import PoliticaDeRepeticao
from domain.material.tipo_arquivo import TipoArquivo
from domain.material_personalizado.material_personalizado import MaterialPersonalizado
from domain.processamento.processamento import Processamento
from domain.shared.exceptions import RecursoNaoEncontradoError

logger = logging.getLogger(__name__)


class PosseDoProcessamentoPerdidaError(Exception):
    """O Worker terminou o trabalho, mas já não é o dono do Processamento.

    A transação do chamador deve ser desfeita: o resultado não pode sobrescrever o que outra
    execução (ou a recuperação de presos) decidiu enquanto este job rodava.
    """


class ProcessarPersonalizacaoUseCase:
    def __init__(
        self,
        processamento_repositorio: IProcessamentoRepository,
        material_repositorio: IMaterialRepository,
        perfil_repositorio: IPerfilRepository,
        material_personalizado_repositorio: IMaterialPersonalizadoRepository,
        storage: IObjectStoragePort,
        llm: ILLMPort,
        politica_de_repeticao: PoliticaDeRepeticao | None = None,
    ) -> None:
        self._processamentos = processamento_repositorio
        self._materiais = material_repositorio
        self._perfis = perfil_repositorio
        self._material_personalizados = material_personalizado_repositorio
        self._storage = storage
        self._llm = llm
        # None = sem repetição: toda falha encerra em erro (comportamento anterior).
        self._politica_de_repeticao = politica_de_repeticao
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

        # perfil_id é o snapshot gravado na criação do Processamento, não o
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
        except FalhaTransitoriaDoProvedorError as falha:
            # Só a chamada ao modelo gera isto (ver GeminiAdapter), antes de qualquer upload: não
            # há PDF a reverter. Erros de extração, PDF, credencial ou Storage NÃO passam por aqui.
            if await self._devolver_para_nova_tentativa(processamento, falha):
                return processamento
            return await self._encerrar_com_erro(processamento)
        except Exception:
            logger.exception(
                "Falha ao processar a personalização do processamento %s.", processamento.id
            )
            return await self._encerrar_com_erro(processamento)

        processamento.marcar_como_concluido()
        if not await self._processamentos.atualizar_se_dono(processamento):
            logger.warning(
                "Posse do processamento %s perdida; o resultado desta execução foi descartado.",
                processamento.id,
            )
            if self.chave_pdf_gerada is not None:
                await self.reverter_upload(self.chave_pdf_gerada)
            raise PosseDoProcessamentoPerdidaError(str(processamento.id))
        return processamento

    async def _devolver_para_nova_tentativa(
        self, processamento: Processamento, falha: FalhaTransitoriaDoProvedorError
    ) -> bool:
        """Devolve o job à fila se ainda houver tentativas e a posse for deste Worker."""
        politica = self._politica_de_repeticao
        tentativas = processamento.tentativas
        if politica is None or not politica.permite_nova_tentativa(tentativas):
            logger.error(
                "Processamento %s encerrado em erro: falha transitória do provedor de IA "
                "(%s, http=%s) com %d tentativa(s) realizada(s).",
                processamento.id,
                falha.categoria.value,
                falha.status_http,
                tentativas,
            )
            return False

        disponivel_em = datetime.now(UTC) + politica.atraso_apos(tentativas)
        devolvido = await self._processamentos.devolver_para_fila_se_dono(
            processamento, disponivel_em, politica.tentativas_maximas
        )
        if not devolvido:
            # Posse perdida ou tentativas esgotadas entre a leitura e a gravação.
            logger.warning(
                "Processamento %s não foi devolvido à fila (posse perdida ou tentativas "
                "esgotadas); a falha transitória (%s) será tratada como erro.",
                processamento.id,
                falha.categoria.value,
            )
            return False

        processamento.devolver_para_nova_tentativa(disponivel_em)
        logger.warning(
            "Processamento %s devolvido à fila após falha transitória do provedor de IA "
            "(%s, http=%s): tentativa %d de %d, próxima a partir de %s.",
            processamento.id,
            falha.categoria.value,
            falha.status_http,
            tentativas,
            politica.tentativas_maximas,
            disponivel_em.isoformat(),
        )
        return True

    async def _encerrar_com_erro(self, processamento: Processamento) -> Processamento:
        processamento.marcar_como_erro("Falha ao processar a personalização do material.")
        if not await self._processamentos.atualizar_se_dono(processamento):
            # Outra execução já decidiu o destino: este erro não deve sobrescrevê-lo.
            logger.warning(
                "Posse do processamento %s perdida; o erro desta execução não foi gravado.",
                processamento.id,
            )
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
