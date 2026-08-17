from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from application.ports.queue import IQueuePort
from domain.processamento.status_processamento import StatusProcessamento
from infrastructure.database.models.processamento import Processamento as ProcessamentoModel
from infrastructure.queue.models import MensagemFila


class FilaPostgres(IQueuePort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publicar(self, processamento_id: UUID) -> None:
        # SAVEPOINT: uma falha real de banco aqui (ex.: violação de constraint)
        # não pode envenenar a transação externa — o chamador (ex.:
        # CriarProcessamentoUseCase) precisa da sessão ainda utilizável para
        # marcar o Processamento como erro logo em seguida.
        async with self._session.begin_nested():
            self._session.add(MensagemFila(id=uuid4(), processamento_id=processamento_id))
            await self._session.flush()

    async def reivindicar_proximo(self) -> UUID | None:
        # UPDATE condicional: só um Worker consegue transicionar uma dada linha
        # de pendente -> em_processamento. FOR UPDATE SKIP LOCKED evita que dois
        # Workers concorrentes disputem a mesma linha candidata na subquery.
        candidato = (
            select(ProcessamentoModel.id)
            .select_from(ProcessamentoModel)
            .join(MensagemFila, MensagemFila.processamento_id == ProcessamentoModel.id)
            .where(ProcessamentoModel.status == StatusProcessamento.PENDENTE.value)
            .order_by(MensagemFila.criado_em.asc())
            .limit(1)
            .with_for_update(of=ProcessamentoModel, skip_locked=True)
        )
        instrucao = (
            update(ProcessamentoModel)
            .where(ProcessamentoModel.id == candidato.scalar_subquery())
            .values(status=StatusProcessamento.EM_PROCESSAMENTO.value, inicio=func.now())
            .returning(ProcessamentoModel.id)
        )
        resultado = await self._session.execute(instrucao)
        processamento_id = resultado.scalar_one_or_none()
        await self._session.flush()
        return processamento_id

    async def remover(self, processamento_id: UUID) -> None:
        instrucao = delete(MensagemFila).where(MensagemFila.processamento_id == processamento_id)
        await self._session.execute(instrucao)
        await self._session.flush()
