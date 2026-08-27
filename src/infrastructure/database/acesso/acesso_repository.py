from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from application.ports.acesso_repository import IAcessoRepository
from domain.acesso.acesso_material_personalizado import AcessoMaterialPersonalizado
from domain.acesso.status_leitura import StatusLeitura
from infrastructure.database.models.acesso import (
    AcessoMaterialPersonalizado as AcessoModel,
)


class AcessoRepositorySQLAlchemy(IAcessoRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def adicionar(self, acesso: AcessoMaterialPersonalizado) -> None:
        self._session.add(_para_modelo(acesso))
        await self._session.flush()

    async def atualizar(self, acesso: AcessoMaterialPersonalizado) -> None:
        modelo = await self._session.get(AcessoModel, acesso.id)
        if modelo is None:
            raise LookupError(f"Acesso {acesso.id} não encontrado para atualização.")
        modelo.data_ultimo_acesso = acesso.data_ultimo_acesso
        modelo.tempo_total_leitura = acesso.tempo_total_leitura
        modelo.quantidade_acessos = acesso.quantidade_acessos
        modelo.porcentagem_leitura = acesso.porcentagem_leitura
        modelo.download_realizado = acesso.download_realizado
        modelo.status_leitura = acesso.status_leitura.value
        await self._session.flush()

    async def obter_por_material_personalizado_id_e_aluno_id(
        self, material_personalizado_id: UUID, aluno_id: UUID
    ) -> AcessoMaterialPersonalizado | None:
        # Chave natural do registro (Documento 3 §4.7), não a PK — session.get()
        # não serve aqui.
        resultado = await self._session.execute(
            select(AcessoModel).where(
                AcessoModel.material_personalizado_id == material_personalizado_id,
                AcessoModel.aluno_id == aluno_id,
            )
        )
        modelo = resultado.scalar_one_or_none()
        return _para_dominio(modelo) if modelo is not None else None

    async def obter_por_material_personalizado_id(
        self, material_personalizado_id: UUID
    ) -> AcessoMaterialPersonalizado | None:
        resultado = await self._session.execute(
            select(AcessoModel).where(
                AcessoModel.material_personalizado_id == material_personalizado_id
            )
        )
        modelo = resultado.scalar_one_or_none()
        return _para_dominio(modelo) if modelo is not None else None


def _para_dominio(modelo: AcessoModel) -> AcessoMaterialPersonalizado:
    return AcessoMaterialPersonalizado(
        id=modelo.id,
        material_personalizado_id=modelo.material_personalizado_id,
        aluno_id=modelo.aluno_id,
        data_primeiro_acesso=modelo.data_primeiro_acesso,
        data_ultimo_acesso=modelo.data_ultimo_acesso,
        tempo_total_leitura=modelo.tempo_total_leitura,
        quantidade_acessos=modelo.quantidade_acessos,
        # A coluna é Numeric(5, 4) (Documento 4 §8 — precisão exata nos limites
        # 0%/100%); o driver assíncrono devolve Decimal, não float. A entidade
        # de Domínio usa float (Documento 3 §4.7 representa a fração em JSON
        # puro, ex.: 0.78) — a conversão pertence a esta borda, não ao Domínio.
        porcentagem_leitura=float(modelo.porcentagem_leitura),
        download_realizado=modelo.download_realizado,
        status_leitura=StatusLeitura(modelo.status_leitura),
    )


def _para_modelo(acesso: AcessoMaterialPersonalizado) -> AcessoModel:
    return AcessoModel(
        id=acesso.id,
        material_personalizado_id=acesso.material_personalizado_id,
        aluno_id=acesso.aluno_id,
        data_primeiro_acesso=acesso.data_primeiro_acesso,
        data_ultimo_acesso=acesso.data_ultimo_acesso,
        tempo_total_leitura=acesso.tempo_total_leitura,
        quantidade_acessos=acesso.quantidade_acessos,
        porcentagem_leitura=acesso.porcentagem_leitura,
        download_realizado=acesso.download_realizado,
        status_leitura=acesso.status_leitura.value,
    )
