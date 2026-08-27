from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from application.log.listar_logs_do_processamento import (
    ListarLogsDoProcessamentoInput,
    ListarLogsDoProcessamentoUseCase,
)
from application.log.registrar_log import RegistrarLogInput, RegistrarLogUseCase
from application.ports.aluno_repository import IAlunoRepository
from application.ports.log_repository import ILogRepository
from application.ports.processamento_repository import IProcessamentoRepository
from infrastructure.database.aluno.aluno_repository import AlunoRepositorySQLAlchemy
from infrastructure.database.log.log_repository import LogRepositorySQLAlchemy
from infrastructure.database.processamento.processamento_repository import (
    ProcessamentoRepositorySQLAlchemy,
)
from infrastructure.database.session import get_db_session
from presentation.api.dependencies import validar_token_servico
from presentation.api.schemas.log import (
    LogCadastroRequest,
    LogListagemResponse,
    LogResponse,
    PaginacaoResponse,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["Log de Interação"],
    dependencies=[Depends(validar_token_servico)],
)


async def _repositorio_aluno(session: AsyncSession = Depends(get_db_session)) -> IAlunoRepository:
    return AlunoRepositorySQLAlchemy(session)


async def _repositorio_processamento(
    session: AsyncSession = Depends(get_db_session),
) -> IProcessamentoRepository:
    return ProcessamentoRepositorySQLAlchemy(session)


async def _repositorio_log(session: AsyncSession = Depends(get_db_session)) -> ILogRepository:
    return LogRepositorySQLAlchemy(session)


@router.post("/logs", response_model=LogResponse, status_code=status.HTTP_201_CREATED)
async def registrar_log(
    dados: LogCadastroRequest,
    repositorio_aluno: IAlunoRepository = Depends(_repositorio_aluno),
    repositorio_processamento: IProcessamentoRepository = Depends(_repositorio_processamento),
    repositorio_log: ILogRepository = Depends(_repositorio_log),
) -> LogResponse:
    log = await RegistrarLogUseCase(
        repositorio_aluno, repositorio_processamento, repositorio_log
    ).executar(
        RegistrarLogInput(
            aluno_id=dados.aluno_id,
            processamento_id=dados.processamento_id,
            acao=dados.acao,
            descricao=dados.descricao,
        )
    )
    return LogResponse.model_validate(log)


@router.get("/processamentos/{id}/logs", response_model=LogListagemResponse)
async def listar_logs_do_processamento(
    id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    repositorio_processamento: IProcessamentoRepository = Depends(_repositorio_processamento),
    repositorio_log: ILogRepository = Depends(_repositorio_log),
) -> LogListagemResponse:
    resultado = await ListarLogsDoProcessamentoUseCase(
        repositorio_processamento, repositorio_log
    ).executar(
        ListarLogsDoProcessamentoInput(processamento_id=id, pagina=page, tamanho_pagina=page_size)
    )
    total_pages = ceil(resultado.total_itens / page_size) if resultado.total_itens else 0
    return LogListagemResponse(
        data=[LogResponse.model_validate(log) for log in resultado.itens],
        pagination=PaginacaoResponse(
            page=page,
            page_size=page_size,
            total_items=resultado.total_itens,
            total_pages=total_pages,
        ),
    )
