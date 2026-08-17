import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from application.ports.aluno_repository import IAlunoRepository
from application.ports.material_repository import IMaterialRepository
from application.ports.perfil_repository import IPerfilRepository
from application.ports.processamento_repository import IProcessamentoRepository
from application.ports.queue import IQueuePort
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from domain.shared.exceptions import RecursoNaoEncontradoError, RegraDeNegocioVioladaError

logger = logging.getLogger(__name__)


@dataclass
class CriarProcessamentoInput:
    aluno_id: UUID
    material_didatico_id: UUID


class CriarProcessamentoUseCase:
    def __init__(
        self,
        aluno_repositorio: IAlunoRepository,
        perfil_repositorio: IPerfilRepository,
        material_repositorio: IMaterialRepository,
        processamento_repositorio: IProcessamentoRepository,
        fila: IQueuePort,
    ) -> None:
        self._aluno_repositorio = aluno_repositorio
        self._perfil_repositorio = perfil_repositorio
        self._material_repositorio = material_repositorio
        self._processamento_repositorio = processamento_repositorio
        self._fila = fila

    async def executar(self, dados: CriarProcessamentoInput) -> Processamento:
        aluno = await self._aluno_repositorio.obter_por_id(dados.aluno_id)
        if aluno is None:
            raise RecursoNaoEncontradoError(
                code="ALUNO_NAO_ENCONTRADO",
                message="Aluno não encontrado.",
                details={"aluno_id": str(dados.aluno_id)},
            )

        perfil = await self._perfil_repositorio.obter_mais_recente_por_aluno_id(dados.aluno_id)
        if perfil is None:
            raise RegraDeNegocioVioladaError(
                code="PERFIL_NAO_CADASTRADO",
                message="O aluno precisa responder ao questionário de estilo de "
                "aprendizagem antes de solicitar uma personalização.",
                details={"aluno_id": str(dados.aluno_id)},
            )

        material = await self._material_repositorio.obter_por_id(dados.material_didatico_id)
        if material is None:
            raise RecursoNaoEncontradoError(
                code="MATERIAL_NAO_ENCONTRADO",
                message="Material didático não encontrado.",
                details={"material_didatico_id": str(dados.material_didatico_id)},
            )

        processamento = Processamento(
            id=uuid4(),
            aluno_id=dados.aluno_id,
            material_didatico_id=dados.material_didatico_id,
            perfil_id=perfil.id,
            status=StatusProcessamento.PENDENTE,
            modelo_ia=None,
            data_criacao=datetime.now(UTC),
            inicio=None,
            fim=None,
            erro=None,
        )
        await self._processamento_repositorio.adicionar(processamento)

        try:
            await self._fila.publicar(processamento.id)
        except Exception:
            # Falha aqui não pode propagar: o registro já foi persistido e
            # precisa sair da transação como "erro", não ser desfeito por ela.
            logger.exception("Falha ao publicar o processamento %s na fila.", processamento.id)
            processamento.marcar_como_erro(
                "Falha ao publicar a solicitação na fila de processamento."
            )
            await self._processamento_repositorio.atualizar(processamento)

        return processamento
