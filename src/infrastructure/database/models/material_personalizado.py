from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.database.base import Base

if TYPE_CHECKING:
    from infrastructure.database.models.acesso import AcessoMaterialPersonalizado
    from infrastructure.database.models.processamento import Processamento


class MaterialPersonalizado(Base):
    """PDF adaptado ao perfil do aluno, em relação 1:1 com o Processamento (Documento 2, §4.1)."""

    __tablename__ = "material_personalizado"
    __table_args__ = (
        # UNIQUE em processamento_id expressa a cardinalidade 1:1 e já serve como
        # índice de busca por FK — um Index separado seria redundante (mesma
        # coluna à esquerda).
        UniqueConstraint("processamento_id", name="uq_material_personalizado_processamento_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    processamento_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "processamento.id",
            ondelete="RESTRICT",
            name="fk_material_personalizado_processamento_id",
        ),
        nullable=False,
    )
    titulo: Mapped[str] = mapped_column(String(255), nullable=False)
    # URL assinada com expiração (Documento 3, §7) — carrega querystring de
    # assinatura, por isso o mesmo teto generoso de MaterialDidatico.caminho_storage.
    caminho_pdf: Mapped[str] = mapped_column(String(500), nullable=False)
    # Resumo de um documento inteiro: tamanho não previsível, Text.
    resumo: Mapped[str] = mapped_column(Text, nullable=False)
    data_geracao: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    processamento: Mapped["Processamento"] = relationship(back_populates="material_personalizado")
    acesso: Mapped["AcessoMaterialPersonalizado | None"] = relationship(
        back_populates="material_personalizado", uselist=False
    )
