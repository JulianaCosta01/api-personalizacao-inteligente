from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from application.ports.processamento_repository import IProcessamentoRepository
from domain.processamento.processamento import Processamento
from domain.processamento.status_processamento import StatusProcessamento
from infrastructure.database.models.processamento import Processamento as ProcessamentoModel


class ProcessamentoRepositorySQLAlchemy(IProcessamentoRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def adicionar(self, processamento: Processamento) -> None:
        self._session.add(_para_modelo(processamento))
        await self._session.flush()

    async def atualizar(self, processamento: Processamento) -> None:
        modelo = await self._session.get(ProcessamentoModel, processamento.id)
        if modelo is None:
            raise LookupError(f"Processamento {processamento.id} não encontrado para atualização.")
        modelo.status = processamento.status.value
        modelo.modelo_ia = processamento.modelo_ia
        modelo.inicio = processamento.inicio
        modelo.fim = processamento.fim
        modelo.erro = processamento.erro
        await self._session.flush()

    async def atualizar_se_dono(self, processamento: Processamento) -> bool:
        # UPDATE condicional atômico: só grava se a linha ainda é a reivindicação que este objeto
        # carrega (status em_processamento e o mesmo `inicio`). Não passa pelo ORM: evita ler a
        # linha, decidir em memória e sobrescrever o que outra execução gravou nesse intervalo.
        instrucao = (
            update(ProcessamentoModel)
            .where(ProcessamentoModel.id == processamento.id)
            .where(ProcessamentoModel.status == StatusProcessamento.EM_PROCESSAMENTO.value)
            .where(ProcessamentoModel.inicio == processamento.inicio)
            .values(
                status=processamento.status.value,
                modelo_ia=processamento.modelo_ia,
                fim=processamento.fim,
                erro=processamento.erro,
            )
            .returning(ProcessamentoModel.id)
            .execution_options(synchronize_session=False)
        )
        resultado = await self._session.execute(instrucao)
        gravou = resultado.scalar_one_or_none() is not None
        await self._session.flush()
        if gravou:
            # A identidade em memória (expire_on_commit=False) ficaria com valores antigos.
            modelo = await self._session.get(ProcessamentoModel, processamento.id)
            if modelo is not None:
                await self._session.refresh(modelo)
        return gravou

    async def devolver_para_fila_se_dono(
        self, processamento: Processamento, disponivel_em: datetime, tentativas_maximas: int
    ) -> bool:
        # UPDATE condicional atômico (mesma ideia de atualizar_se_dono): só devolve à fila quem
        # ainda é o dono da reivindicação E ainda tem tentativas. O limite é verificado no próprio
        # SQL, então nem uma corrida entre Workers nem um erro de lógica o ultrapassa.
        instrucao = (
            update(ProcessamentoModel)
            .where(ProcessamentoModel.id == processamento.id)
            .where(ProcessamentoModel.status == StatusProcessamento.EM_PROCESSAMENTO.value)
            .where(ProcessamentoModel.inicio == processamento.inicio)
            .where(ProcessamentoModel.tentativas < tentativas_maximas)
            .values(status=StatusProcessamento.PENDENTE.value, disponivel_em=disponivel_em)
            .returning(ProcessamentoModel.id)
            .execution_options(synchronize_session=False)
        )
        resultado = await self._session.execute(instrucao)
        devolvido = resultado.scalar_one_or_none() is not None
        await self._session.flush()
        if devolvido:
            modelo = await self._session.get(ProcessamentoModel, processamento.id)
            if modelo is not None:
                await self._session.refresh(modelo)
        return devolvido

    async def obter_por_id(self, id: UUID) -> Processamento | None:
        modelo = await self._session.get(ProcessamentoModel, id)
        return _para_dominio(modelo) if modelo is not None else None

    async def listar_por_aluno_id(
        self, aluno_id: UUID, pagina: int, tamanho_pagina: int
    ) -> tuple[list[Processamento], int]:
        consulta_total = (
            select(func.count())
            .select_from(ProcessamentoModel)
            .where(ProcessamentoModel.aluno_id == aluno_id)
        )
        total = (await self._session.execute(consulta_total)).scalar_one()

        consulta = (
            select(ProcessamentoModel)
            .where(ProcessamentoModel.aluno_id == aluno_id)
            .order_by(ProcessamentoModel.data_criacao.desc())
            .offset((pagina - 1) * tamanho_pagina)
            .limit(tamanho_pagina)
        )
        modelos = (await self._session.execute(consulta)).scalars().all()
        return [_para_dominio(m) for m in modelos], total

    async def liberar_presos(
        self, idade_maxima: timedelta, tentativas_maximas: int | None = None
    ) -> list[UUID]:
        # Com `tentativas_maximas`, só volta para pendente quem ainda tem tentativas; quem as
        # esgotou é tratado por esgotar_tentativas_dos_presos (chamar essa primeiro).
        limite = datetime.now(UTC) - idade_maxima
        instrucao = (
            update(ProcessamentoModel)
            .where(ProcessamentoModel.status == StatusProcessamento.EM_PROCESSAMENTO.value)
            .where(ProcessamentoModel.inicio < limite)
            .values(status=StatusProcessamento.PENDENTE.value)
            .returning(ProcessamentoModel.id)
        )
        if tentativas_maximas is not None:
            instrucao = instrucao.where(ProcessamentoModel.tentativas < tentativas_maximas)
        resultado = await self._session.execute(instrucao)
        liberados = list(resultado.scalars().all())
        await self._session.flush()
        return liberados

    async def esgotar_tentativas_dos_presos(
        self, idade_maxima: timedelta, tentativas_maximas: int
    ) -> list[UUID]:
        # Job preso que já foi reivindicado `tentativas_maximas` vezes não volta para a fila:
        # encerra em erro, em vez de ser reprocessado para sempre (ex.: PDF que derruba o Worker).
        limite = datetime.now(UTC) - idade_maxima
        instrucao = (
            update(ProcessamentoModel)
            .where(ProcessamentoModel.status == StatusProcessamento.EM_PROCESSAMENTO.value)
            .where(ProcessamentoModel.inicio < limite)
            .where(ProcessamentoModel.tentativas >= tentativas_maximas)
            .values(
                status=StatusProcessamento.ERRO.value,
                fim=func.now(),
                erro="Número máximo de tentativas de processamento excedido.",
            )
            .returning(ProcessamentoModel.id)
        )
        resultado = await self._session.execute(instrucao)
        esgotados = list(resultado.scalars().all())
        await self._session.flush()
        return esgotados


def _para_dominio(modelo: ProcessamentoModel) -> Processamento:
    return Processamento(
        id=modelo.id,
        aluno_id=modelo.aluno_id,
        material_didatico_id=modelo.material_didatico_id,
        perfil_id=modelo.perfil_id,
        status=StatusProcessamento(modelo.status),
        modelo_ia=modelo.modelo_ia,
        data_criacao=modelo.data_criacao,
        inicio=modelo.inicio,
        fim=modelo.fim,
        erro=modelo.erro,
        tentativas=modelo.tentativas,
        disponivel_em=modelo.disponivel_em,
    )


def _para_modelo(processamento: Processamento) -> ProcessamentoModel:
    return ProcessamentoModel(
        id=processamento.id,
        aluno_id=processamento.aluno_id,
        material_didatico_id=processamento.material_didatico_id,
        perfil_id=processamento.perfil_id,
        status=processamento.status.value,
        modelo_ia=processamento.modelo_ia,
        data_criacao=processamento.data_criacao,
        inicio=processamento.inicio,
        fim=processamento.fim,
        erro=processamento.erro,
        tentativas=processamento.tentativas,
    )
