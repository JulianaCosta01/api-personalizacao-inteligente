from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from application.ports.material_repository import IMaterialRepository
from domain.material.material_didatico import MaterialDidatico
from domain.material.tipo_arquivo import TipoArquivo
from infrastructure.database.models.material import MaterialDidatico as MaterialModel


class MaterialRepositorySQLAlchemy(IMaterialRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def obter_por_id(self, id: UUID) -> MaterialDidatico | None:
        modelo = await self._session.get(MaterialModel, id)
        return _para_dominio(modelo) if modelo is not None else None

    async def adicionar(self, material: MaterialDidatico) -> None:
        self._session.add(_para_modelo(material))
        await self._session.flush()

    async def atualizar(self, material: MaterialDidatico) -> None:
        modelo = await self._session.get(MaterialModel, material.id)
        if modelo is None:
            raise LookupError(f"Material {material.id} não encontrado para atualização.")
        modelo.nome_arquivo = material.nome_arquivo
        modelo.tipo_arquivo = material.tipo_arquivo.value
        modelo.caminho_storage = material.caminho_storage
        modelo.versao = material.versao
        modelo.data_upload = material.data_upload
        await self._session.flush()

    async def listar(
        self, pagina: int, tamanho_pagina: int, titulo: str | None
    ) -> tuple[list[MaterialDidatico], int]:
        filtro = MaterialModel.titulo.ilike(f"%{titulo}%") if titulo else None

        consulta_total = select(func.count()).select_from(MaterialModel)
        if filtro is not None:
            consulta_total = consulta_total.where(filtro)
        total = (await self._session.execute(consulta_total)).scalar_one()

        consulta = select(MaterialModel).order_by(MaterialModel.data_upload.desc())
        if filtro is not None:
            consulta = consulta.where(filtro)
        consulta = consulta.offset((pagina - 1) * tamanho_pagina).limit(tamanho_pagina)
        modelos = (await self._session.execute(consulta)).scalars().all()

        return [_para_dominio(m) for m in modelos], total


def _para_dominio(modelo: MaterialModel) -> MaterialDidatico:
    return MaterialDidatico(
        id=modelo.id,
        titulo=modelo.titulo,
        nome_arquivo=modelo.nome_arquivo,
        tipo_arquivo=TipoArquivo(modelo.tipo_arquivo),
        caminho_storage=modelo.caminho_storage,
        versao=modelo.versao,
        data_upload=modelo.data_upload,
    )


def _para_modelo(material: MaterialDidatico) -> MaterialModel:
    return MaterialModel(
        id=material.id,
        titulo=material.titulo,
        nome_arquivo=material.nome_arquivo,
        tipo_arquivo=material.tipo_arquivo.value,
        caminho_storage=material.caminho_storage,
        versao=material.versao,
        data_upload=material.data_upload,
    )
