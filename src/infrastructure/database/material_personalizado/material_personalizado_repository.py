from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from application.ports.material_personalizado_repository import IMaterialPersonalizadoRepository
from domain.material_personalizado.material_personalizado import MaterialPersonalizado
from infrastructure.database.models.material_personalizado import (
    MaterialPersonalizado as MaterialPersonalizadoModel,
)


class MaterialPersonalizadoRepositorySQLAlchemy(IMaterialPersonalizadoRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def adicionar(self, material_personalizado: MaterialPersonalizado) -> None:
        # SAVEPOINT: uma falha real de banco aqui (ex.: violação da unicidade de
        # processamento_id) não pode envenenar a transação externa — o chamador
        # (ProcessarPersonalizacaoUseCase) precisa da sessão ainda utilizável
        # para marcar o Processamento como erro logo em seguida.
        async with self._session.begin_nested():
            self._session.add(_para_modelo(material_personalizado))
            await self._session.flush()

    async def obter_por_id(self, id: UUID) -> MaterialPersonalizado | None:
        modelo = await self._session.get(MaterialPersonalizadoModel, id)
        return _para_dominio(modelo) if modelo is not None else None

    async def obter_por_processamento_id(
        self, processamento_id: UUID
    ) -> MaterialPersonalizado | None:
        # processamento_id não é a PK do modelo (é UNIQUE, Documento 4 §8) —
        # não dá para usar session.get(), que só busca por chave primária.
        resultado = await self._session.execute(
            select(MaterialPersonalizadoModel).where(
                MaterialPersonalizadoModel.processamento_id == processamento_id
            )
        )
        modelo = resultado.scalar_one_or_none()
        return _para_dominio(modelo) if modelo is not None else None


def _para_dominio(modelo: MaterialPersonalizadoModel) -> MaterialPersonalizado:
    return MaterialPersonalizado(
        id=modelo.id,
        processamento_id=modelo.processamento_id,
        titulo=modelo.titulo,
        caminho_pdf=modelo.caminho_pdf,
        resumo=modelo.resumo,
        data_geracao=modelo.data_geracao,
    )


def _para_modelo(material_personalizado: MaterialPersonalizado) -> MaterialPersonalizadoModel:
    return MaterialPersonalizadoModel(
        id=material_personalizado.id,
        processamento_id=material_personalizado.processamento_id,
        titulo=material_personalizado.titulo,
        caminho_pdf=material_personalizado.caminho_pdf,
        resumo=material_personalizado.resumo,
        data_geracao=material_personalizado.data_geracao,
    )
