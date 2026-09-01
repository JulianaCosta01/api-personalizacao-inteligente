from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from application.perfil.consultar_perfil_mais_recente import ConsultarPerfilMaisRecenteUseCase
from application.perfil.criar_perfil import CriarPerfilInput, CriarPerfilUseCase
from application.perfil.listar_perfis import ListarPerfisInput, ListarPerfisUseCase
from application.ports.aluno_repository import IAlunoRepository
from application.ports.llm import ILLMPort
from application.ports.perfil_repository import IPerfilRepository
from core.config import Settings, get_settings
from infrastructure.database.aluno.aluno_repository import AlunoRepositorySQLAlchemy
from infrastructure.database.perfil.perfil_repository import PerfilRepositorySQLAlchemy
from infrastructure.database.session import get_db_session
from infrastructure.llm.cliente import get_gemini_client
from infrastructure.llm.gemini_adapter import GeminiAdapter
from presentation.api.dependencies import validar_token_servico
from presentation.api.schemas.perfil import (
    PaginacaoResponse,
    PerfilCadastroRequest,
    PerfilListagemResponse,
    PerfilResponse,
)

router = APIRouter(
    prefix="/api/v1/alunos",
    tags=["Perfil de Aprendizagem"],
    dependencies=[Depends(validar_token_servico)],
)


async def _repositorio_aluno(session: AsyncSession = Depends(get_db_session)) -> IAlunoRepository:
    return AlunoRepositorySQLAlchemy(session)


async def _repositorio_perfil(
    session: AsyncSession = Depends(get_db_session),
) -> IPerfilRepository:
    return PerfilRepositorySQLAlchemy(session)


def _llm(settings: Settings = Depends(get_settings)) -> ILLMPort:
    # timeout_total_segundos não é passado de propósito: este é o caminho síncrono (Documento 3
    # §4.2 exige tempo-limite curto), diferente do Worker, que tem espaço para o retry completo.
    return GeminiAdapter(
        get_gemini_client(), settings.gemini_model, settings.gemini_timeout_segundos
    )


@router.post(
    "/{aluno_id}/perfil", response_model=PerfilResponse, status_code=status.HTTP_201_CREATED
)
async def cadastrar_perfil(
    aluno_id: UUID,
    dados: PerfilCadastroRequest,
    repositorio_aluno: IAlunoRepository = Depends(_repositorio_aluno),
    repositorio_perfil: IPerfilRepository = Depends(_repositorio_perfil),
    llm: ILLMPort = Depends(_llm),
) -> PerfilResponse:
    perfil = await CriarPerfilUseCase(repositorio_aluno, repositorio_perfil, llm).executar(
        CriarPerfilInput(
            aluno_id=aluno_id,
            estilo_processamento=dados.estilo_processamento,
            percepcao=dados.percepcao,
            entrada=dados.entrada,
            compreensao=dados.compreensao,
        )
    )
    return PerfilResponse.model_validate(perfil)


@router.get("/{aluno_id}/perfil", response_model=PerfilResponse)
async def consultar_perfil_mais_recente(
    aluno_id: UUID,
    repositorio_aluno: IAlunoRepository = Depends(_repositorio_aluno),
    repositorio_perfil: IPerfilRepository = Depends(_repositorio_perfil),
) -> PerfilResponse:
    perfil = await ConsultarPerfilMaisRecenteUseCase(
        repositorio_aluno, repositorio_perfil
    ).executar(aluno_id)
    return PerfilResponse.model_validate(perfil)


@router.get("/{aluno_id}/perfis", response_model=PerfilListagemResponse)
async def listar_perfis(
    aluno_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    repositorio_aluno: IAlunoRepository = Depends(_repositorio_aluno),
    repositorio_perfil: IPerfilRepository = Depends(_repositorio_perfil),
) -> PerfilListagemResponse:
    resultado = await ListarPerfisUseCase(repositorio_aluno, repositorio_perfil).executar(
        ListarPerfisInput(aluno_id=aluno_id, pagina=page, tamanho_pagina=page_size)
    )
    total_pages = ceil(resultado.total_itens / page_size) if resultado.total_itens else 0
    return PerfilListagemResponse(
        data=[PerfilResponse.model_validate(p) for p in resultado.itens],
        pagination=PaginacaoResponse(
            page=page,
            page_size=page_size,
            total_items=resultado.total_itens,
            total_pages=total_pages,
        ),
    )
