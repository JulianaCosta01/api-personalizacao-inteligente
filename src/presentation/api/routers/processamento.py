from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from application.ports.aluno_repository import IAlunoRepository
from application.ports.material_repository import IMaterialRepository
from application.ports.perfil_repository import IPerfilRepository
from application.ports.processamento_repository import IProcessamentoRepository
from application.ports.queue import IQueuePort
from application.processamento.consultar_processamento import ConsultarProcessamentoUseCase
from application.processamento.criar_processamento import (
    CriarProcessamentoInput,
    CriarProcessamentoUseCase,
)
from application.processamento.listar_processamentos import (
    ListarProcessamentosDoAlunoUseCase,
    ListarProcessamentosInput,
)
from domain.processamento.status_processamento import StatusProcessamento
from infrastructure.database.aluno.aluno_repository import AlunoRepositorySQLAlchemy
from infrastructure.database.material.material_repository import MaterialRepositorySQLAlchemy
from infrastructure.database.perfil.perfil_repository import PerfilRepositorySQLAlchemy
from infrastructure.database.processamento.processamento_repository import (
    ProcessamentoRepositorySQLAlchemy,
)
from infrastructure.database.session import get_db_session
from infrastructure.queue.fila_postgres import FilaPostgres
from presentation.api.dependencies import validar_token_servico
from presentation.api.rate_limit import limitar_processamentos
from presentation.api.schemas.processamento import (
    PaginacaoResponse,
    ProcessamentoCadastroRequest,
    ProcessamentoListagemResponse,
    ProcessamentoResponse,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["Processamento de Personalização"],
    dependencies=[Depends(validar_token_servico)],
)


async def _repositorio_aluno(session: AsyncSession = Depends(get_db_session)) -> IAlunoRepository:
    return AlunoRepositorySQLAlchemy(session)


async def _repositorio_perfil(
    session: AsyncSession = Depends(get_db_session),
) -> IPerfilRepository:
    return PerfilRepositorySQLAlchemy(session)


async def _repositorio_material(
    session: AsyncSession = Depends(get_db_session),
) -> IMaterialRepository:
    return MaterialRepositorySQLAlchemy(session)


async def _repositorio_processamento(
    session: AsyncSession = Depends(get_db_session),
) -> IProcessamentoRepository:
    return ProcessamentoRepositorySQLAlchemy(session)


async def _fila(session: AsyncSession = Depends(get_db_session)) -> IQueuePort:
    return FilaPostgres(session)


@router.post(
    "/processamentos", response_model=ProcessamentoResponse, status_code=status.HTTP_202_ACCEPTED
)
async def cadastrar_processamento(
    dados: ProcessamentoCadastroRequest,
    response: Response,
    _limite: None = Depends(limitar_processamentos),
    repositorio_aluno: IAlunoRepository = Depends(_repositorio_aluno),
    repositorio_perfil: IPerfilRepository = Depends(_repositorio_perfil),
    repositorio_material: IMaterialRepository = Depends(_repositorio_material),
    repositorio_processamento: IProcessamentoRepository = Depends(_repositorio_processamento),
    fila: IQueuePort = Depends(_fila),
) -> ProcessamentoResponse:
    processamento = await CriarProcessamentoUseCase(
        repositorio_aluno,
        repositorio_perfil,
        repositorio_material,
        repositorio_processamento,
        fila,
    ).executar(
        CriarProcessamentoInput(
            aluno_id=dados.aluno_id, material_didatico_id=dados.material_didatico_id
        )
    )
    # Falha ao publicar já foi persistida como erro pelo Use Case; aqui só traduzimos esse
    # estado para o código HTTP, sem lançar exceção (que desfaria a marcação via rollback).
    if processamento.status == StatusProcessamento.ERRO:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return ProcessamentoResponse.model_validate(processamento)


@router.get("/processamentos/{id}", response_model=ProcessamentoResponse)
async def consultar_processamento(
    id: UUID,
    repositorio_processamento: IProcessamentoRepository = Depends(_repositorio_processamento),
) -> ProcessamentoResponse:
    processamento = await ConsultarProcessamentoUseCase(repositorio_processamento).executar(id)
    return ProcessamentoResponse.model_validate(processamento)


@router.get("/alunos/{aluno_id}/processamentos", response_model=ProcessamentoListagemResponse)
async def listar_processamentos_do_aluno(
    aluno_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    repositorio_aluno: IAlunoRepository = Depends(_repositorio_aluno),
    repositorio_processamento: IProcessamentoRepository = Depends(_repositorio_processamento),
) -> ProcessamentoListagemResponse:
    resultado = await ListarProcessamentosDoAlunoUseCase(
        repositorio_aluno, repositorio_processamento
    ).executar(ListarProcessamentosInput(aluno_id=aluno_id, pagina=page, tamanho_pagina=page_size))
    total_pages = ceil(resultado.total_itens / page_size) if resultado.total_itens else 0
    return ProcessamentoListagemResponse(
        data=[ProcessamentoResponse.model_validate(p) for p in resultado.itens],
        pagination=PaginacaoResponse(
            page=page,
            page_size=page_size,
            total_items=resultado.total_itens,
            total_pages=total_pages,
        ),
    )
