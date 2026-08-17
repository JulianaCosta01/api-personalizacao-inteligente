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


def _para_modelo(material_personalizado: MaterialPersonalizado) -> MaterialPersonalizadoModel:
    return MaterialPersonalizadoModel(
        id=material_personalizado.id,
        processamento_id=material_personalizado.processamento_id,
        titulo=material_personalizado.titulo,
        caminho_pdf=material_personalizado.caminho_pdf,
        resumo=material_personalizado.resumo,
        data_geracao=material_personalizado.data_geracao,
    )
