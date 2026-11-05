import asyncio
from math import ceil
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from application.material.cadastrar_material import (
    CadastrarMaterialInput,
    CadastrarMaterialUseCase,
)
from application.material.consultar_material import ConsultarMaterialUseCase
from application.material.listar_materiais import ListarMateriaisInput, ListarMateriaisUseCase
from application.ports.material_repository import IMaterialRepository
from application.ports.object_storage import IObjectStoragePort
from core.config import Settings, get_settings
from infrastructure.database.material.material_repository import MaterialRepositorySQLAlchemy
from infrastructure.database.session import get_db_session
from infrastructure.pipeline.extrator import contar_paginas
from infrastructure.storage.cliente import get_storage_client
from infrastructure.storage.supabase_storage import SupabaseStorageAdapter
from presentation.api.dependencies import validar_token_servico
from presentation.api.rate_limit import limitar_materiais
from presentation.api.schemas.material import (
    MaterialListagemResponse,
    MaterialResponse,
    PaginacaoResponse,
)

_TAMANHO_BLOCO_LEITURA = 1024 * 1024

router = APIRouter(
    prefix="/api/v1/materiais",
    tags=["Material Didático"],
    dependencies=[Depends(validar_token_servico)],
)


async def _repositorio_material(
    session: AsyncSession = Depends(get_db_session),
) -> IMaterialRepository:
    return MaterialRepositorySQLAlchemy(session)


def _storage_material(settings: Settings = Depends(get_settings)) -> IObjectStoragePort:
    return SupabaseStorageAdapter(get_storage_client(), settings.storage_bucket_materiais)


async def _ler_arquivo(arquivo: UploadFile, limite_bytes: int) -> bytes:
    # Lê em blocos e aborta ao passar do limite, sem confiar no Content-Length do cliente.
    pedacos = bytearray()
    while bloco := await arquivo.read(_TAMANHO_BLOCO_LEITURA):
        pedacos.extend(bloco)
        if len(pedacos) > limite_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "ARQUIVO_MUITO_GRANDE",
                    "message": f"O arquivo excede o limite de {limite_bytes} bytes.",
                },
            )
    return bytes(pedacos)


_TAMANHO_MAXIMO_DO_NOME_DE_ARQUIVO = 255


def nome_de_arquivo_seguro(nome: str | None) -> str:
    """Nome de arquivo informado pelo cliente, reduzido ao que cabe na coluna e sem caminho.

    Só serve para exibição: a chave no Storage nunca deriva dele. Remove diretórios (/ e \\) e
    caracteres de controle, e trunca no tamanho da coluna (255), em vez de falhar no banco.
    """
    ultimo = (nome or "").replace("\\", "/").rsplit("/", 1)[-1]
    limpo = "".join(c for c in ultimo if c.isprintable()).strip()
    return limpo[:_TAMANHO_MAXIMO_DO_NOME_DE_ARQUIVO] or "material.pdf"


async def _exigir_limite_de_paginas(conteudo: bytes, limite: int) -> None:
    # Só rejeita o que se prova excessivo: um arquivo que não abre segue para a validação do
    # caso de uso (e, se passar, falha no pipeline), sem mudar o comportamento atual.
    paginas = await asyncio.to_thread(contar_paginas, conteudo)
    if paginas is not None and paginas > limite:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PDF_PAGINAS_EXCEDIDAS",
                "message": f"O PDF excede o limite de {limite} páginas.",
            },
        )


@router.post("", response_model=MaterialResponse)
async def cadastrar_material(
    response: Response,
    _limite: None = Depends(limitar_materiais),
    titulo: str = Form(..., min_length=1, max_length=255),
    arquivo: UploadFile = File(...),
    material_original_id: UUID | None = Form(default=None),
    settings: Settings = Depends(get_settings),
    repositorio: IMaterialRepository = Depends(_repositorio_material),
    storage: IObjectStoragePort = Depends(_storage_material),
) -> MaterialResponse:
    conteudo = await _ler_arquivo(arquivo, settings.material_tamanho_maximo_bytes)
    await _exigir_limite_de_paginas(conteudo, settings.pdf_paginas_maximas)

    material = await CadastrarMaterialUseCase(repositorio, storage).executar(
        CadastrarMaterialInput(
            titulo=titulo,
            nome_arquivo=nome_de_arquivo_seguro(arquivo.filename),
            conteudo=conteudo,
            material_original_id=material_original_id,
        )
    )

    # Revisão de um material existente não cria um recurso novo (mesmo id)
    response.status_code = (
        status.HTTP_200_OK if material_original_id is not None else status.HTTP_201_CREATED
    )
    return MaterialResponse.model_validate(material)


@router.get("/{id}", response_model=MaterialResponse)
async def consultar_material(
    id: UUID, repositorio: IMaterialRepository = Depends(_repositorio_material)
) -> MaterialResponse:
    material = await ConsultarMaterialUseCase(repositorio).executar(id)
    return MaterialResponse.model_validate(material)


@router.get("", response_model=MaterialListagemResponse)
async def listar_materiais(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    titulo: str | None = Query(default=None, max_length=255),
    repositorio: IMaterialRepository = Depends(_repositorio_material),
) -> MaterialListagemResponse:
    resultado = await ListarMateriaisUseCase(repositorio).executar(
        ListarMateriaisInput(pagina=page, tamanho_pagina=page_size, titulo=titulo)
    )
    total_pages = ceil(resultado.total_itens / page_size) if resultado.total_itens else 0
    return MaterialListagemResponse(
        data=[MaterialResponse.model_validate(m) for m in resultado.itens],
        pagination=PaginacaoResponse(
            page=page,
            page_size=page_size,
            total_items=resultado.total_itens,
            total_pages=total_pages,
        ),
    )
