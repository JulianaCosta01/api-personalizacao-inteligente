from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from application.material_personalizado.consultar_material_personalizado import (
    ConsultarMaterialPersonalizadoUseCase,
)
from application.material_personalizado.consultar_material_personalizado_do_processamento import (
    ConsultarMaterialPersonalizadoDoProcessamentoUseCase,
)
from application.ports.material_personalizado_repository import IMaterialPersonalizadoRepository
from application.ports.object_storage import IObjectStoragePort
from application.ports.processamento_repository import IProcessamentoRepository
from core.config import Settings, get_settings
from domain.material_personalizado.material_personalizado import MaterialPersonalizado
from infrastructure.database.material_personalizado.material_personalizado_repository import (
    MaterialPersonalizadoRepositorySQLAlchemy,
)
from infrastructure.database.processamento.processamento_repository import (
    ProcessamentoRepositorySQLAlchemy,
)
from infrastructure.database.session import get_db_session
from infrastructure.storage.cliente import get_storage_client
from infrastructure.storage.supabase_storage import SupabaseStorageAdapter
from presentation.api.dependencies import validar_token_servico
from presentation.api.schemas.material_personalizado import MaterialPersonalizadoResponse

router = APIRouter(
    prefix="/api/v1",
    tags=["Material Personalizado"],
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


def _storage_material_personalizado(
    settings: Settings = Depends(get_settings),
) -> IObjectStoragePort:
    # Mesmo bucket dos materiais didáticos: o Worker grava em "materiais-personalizados/{id}.pdf"
    # dentro dele (ver ProcessarPersonalizacaoUseCase); não há bucket dedicado em Settings.
    return SupabaseStorageAdapter(get_storage_client(), settings.storage_bucket_materiais)


async def _resposta_com_url_assinada(
    material: MaterialPersonalizado, storage: IObjectStoragePort, settings: Settings
) -> MaterialPersonalizadoResponse:
    url_assinada = await storage.criar_url_leitura(
        material.caminho_pdf, settings.url_leitura_expiracao_segundos
    )
    resposta = MaterialPersonalizadoResponse.model_validate(material)
    resposta.caminho_pdf = url_assinada
    return resposta


@router.get(
    "/processamentos/{id}/material",
    response_model=MaterialPersonalizadoResponse,
)
async def consultar_material_personalizado_do_processamento(
    id: UUID,
    repositorio_processamento: IProcessamentoRepository = Depends(_repositorio_processamento),
    repositorio_material_personalizado: IMaterialPersonalizadoRepository = Depends(
        _repositorio_material_personalizado
    ),
    storage: IObjectStoragePort = Depends(_storage_material_personalizado),
    settings: Settings = Depends(get_settings),
) -> MaterialPersonalizadoResponse:
    material = await ConsultarMaterialPersonalizadoDoProcessamentoUseCase(
        repositorio_processamento, repositorio_material_personalizado
    ).executar(id)
    return await _resposta_com_url_assinada(material, storage, settings)


@router.get(
    "/materiais-personalizados/{id}",
    response_model=MaterialPersonalizadoResponse,
)
async def consultar_material_personalizado(
    id: UUID,
    repositorio_material_personalizado: IMaterialPersonalizadoRepository = Depends(
        _repositorio_material_personalizado
    ),
    storage: IObjectStoragePort = Depends(_storage_material_personalizado),
    settings: Settings = Depends(get_settings),
) -> MaterialPersonalizadoResponse:
    material = await ConsultarMaterialPersonalizadoUseCase(
        repositorio_material_personalizado
    ).executar(id)
    return await _resposta_com_url_assinada(material, storage, settings)
