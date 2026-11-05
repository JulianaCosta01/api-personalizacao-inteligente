from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from application.acesso.consultar_acesso import ConsultarAcessoUseCase
from application.acesso.registrar_acesso import RegistrarAcessoInput, RegistrarAcessoUseCase
from application.ports.acesso_repository import IAcessoRepository
from application.ports.material_personalizado_repository import IMaterialPersonalizadoRepository
from application.ports.processamento_repository import IProcessamentoRepository
from infrastructure.database.acesso.acesso_repository import AcessoRepositorySQLAlchemy
from infrastructure.database.material_personalizado.material_personalizado_repository import (
    MaterialPersonalizadoRepositorySQLAlchemy,
)
from infrastructure.database.processamento.processamento_repository import (
    ProcessamentoRepositorySQLAlchemy,
)
from infrastructure.database.session import get_db_session
from presentation.api.dependencies import validar_token_servico
from presentation.api.schemas.acesso import AcessoAtualizacaoRequest, AcessoResponse

router = APIRouter(
    prefix="/api/v1",
    tags=["Acesso ao Material Personalizado"],
    dependencies=[Depends(validar_token_servico)],
)


async def _repositorio_processamento(
    session: AsyncSession = Depends(get_db_session),
) -> IProcessamentoRepository:
    return ProcessamentoRepositorySQLAlchemy(session)


async def _repositorio_material_personalizado(
    session: AsyncSession = Depends(get_db_session),
) -> IMaterialPersonalizadoRepository:
    return MaterialPersonalizadoRepositorySQLAlchemy(session)


async def _repositorio_acesso(
    session: AsyncSession = Depends(get_db_session),
) -> IAcessoRepository:
    return AcessoRepositorySQLAlchemy(session)


@router.get("/materiais-personalizados/{id}/acesso", response_model=AcessoResponse)
async def consultar_acesso(
    id: UUID,
    repositorio_acesso: IAcessoRepository = Depends(_repositorio_acesso),
) -> AcessoResponse:
    acesso = await ConsultarAcessoUseCase(repositorio_acesso).executar(id)
    return AcessoResponse.model_validate(acesso)


@router.put("/materiais-personalizados/{id}/acesso", response_model=AcessoResponse)
async def registrar_acesso(
    id: UUID,
    dados: AcessoAtualizacaoRequest,
    response: Response,
    repositorio_processamento: IProcessamentoRepository = Depends(_repositorio_processamento),
    repositorio_material_personalizado: IMaterialPersonalizadoRepository = Depends(
        _repositorio_material_personalizado
    ),
    repositorio_acesso: IAcessoRepository = Depends(_repositorio_acesso),
) -> AcessoResponse:
    resultado = await RegistrarAcessoUseCase(
        repositorio_processamento, repositorio_material_personalizado, repositorio_acesso
    ).executar(
        RegistrarAcessoInput(
            material_personalizado_id=id,
            aluno_id=dados.aluno_id,
            tempo_leitura_incremento_segundos=dados.tempo_leitura_incremento_segundos,
            porcentagem_leitura=dados.porcentagem_leitura,
            download_realizado=dados.download_realizado,
        )
    )
    # 201 no primeiro registro, 200 nas atualizações seguintes;
    # mesma convenção de POST /materiais (revisão vs. criação) e do upsert de POST /alunos.
    response.status_code = status.HTTP_201_CREATED if resultado.criado else status.HTTP_200_OK
    return AcessoResponse.model_validate(resultado.acesso)
