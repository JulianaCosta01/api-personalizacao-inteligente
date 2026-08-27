import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from application.ports.aluno_repository import IAlunoRepository
from application.ports.log_repository import ILogRepository
from application.ports.processamento_repository import IProcessamentoRepository
from domain.log.log_interacao import LogInteracao
from domain.shared.exceptions import EntradaInvalidaError, RecursoNaoEncontradoError

logger = logging.getLogger(__name__)


@dataclass
class RegistrarLogInput:
    aluno_id: UUID
    processamento_id: UUID | None
    acao: str
    descricao: str | None


class RegistrarLogUseCase:
    def __init__(
        self,
        aluno_repositorio: IAlunoRepository,
        processamento_repositorio: IProcessamentoRepository,
        log_repositorio: ILogRepository,
    ) -> None:
        self._aluno_repositorio = aluno_repositorio
        self._processamento_repositorio = processamento_repositorio
        self._log_repositorio = log_repositorio

    async def executar(self, dados: RegistrarLogInput) -> LogInteracao:
        aluno = await self._aluno_repositorio.obter_por_id(dados.aluno_id)
        if aluno is None:
            raise RecursoNaoEncontradoError(
                code="ALUNO_NAO_ENCONTRADO",
                message="Aluno não encontrado.",
                details={"aluno_id": str(dados.aluno_id)},
            )

        if dados.processamento_id is not None:
            # Documento 3 §4.6: processamento_id é opcional, mas quando informado
            # deve corresponder a um processamento existente.
            processamento = await self._processamento_repositorio.obter_por_id(
                dados.processamento_id
            )
            if processamento is None:
                raise RecursoNaoEncontradoError(
                    code="PROCESSAMENTO_NAO_ENCONTRADO",
                    message="Processamento não encontrado.",
                    details={"processamento_id": str(dados.processamento_id)},
                )

            if processamento.aluno_id != dados.aluno_id:
                # Fase 9 Task 4A: aluno_id e processamento_id eram validados de
                # forma independente (cada um só contra sua própria existência),
                # sem nunca serem cruzados entre si — permitindo registrar um log
                # com aluno_id de uma pessoa e processamento_id de outra,
                # corrompendo a auditoria de negócio. Mesmo padrão de proteção já
                # usado em RegistrarAcessoUseCase (Documento 4, §13.2).
                logger.warning(
                    "Tentativa de registrar log com aluno_id %s divergente do "
                    "dono %s do processamento %s (possível BOLA/IDOR).",
                    dados.aluno_id,
                    processamento.aluno_id,
                    dados.processamento_id,
                )
                raise EntradaInvalidaError(
                    code="ALUNO_ID_INVALIDO",
                    message="aluno_id não corresponde ao aluno do processamento informado.",
                    details={
                        "aluno_id": str(dados.aluno_id),
                        "processamento_id": str(dados.processamento_id),
                    },
                )

        log = LogInteracao(
            id=uuid4(),
            aluno_id=dados.aluno_id,
            processamento_id=dados.processamento_id,
            acao=dados.acao,
            descricao=dados.descricao,
            timestamp=datetime.now(UTC),
        )
        await self._log_repositorio.adicionar(log)
        return log
