from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.database.base import Base

if TYPE_CHECKING:
    from infrastructure.database.models.aluno import Aluno
    from infrastructure.database.models.material_personalizado import MaterialPersonalizado


class AcessoMaterialPersonalizado(Base):
    """Histórico de leitura de um Material Personalizado.

    A linha só passa a existir no primeiro PUT .../acesso;
    não há criação antecipada ao gerar o Material Personalizado.
    """

    __tablename__ = "acesso"
    __table_args__ = (
        # Chave natural: material_personalizado_id + aluno_id. Sem esta UNIQUE o 1:1
        # ficaria garantido só indiretamente.
        UniqueConstraint(
            "material_personalizado_id",
            "aluno_id",
            name="uq_acesso_material_personalizado_id_aluno_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    material_personalizado_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "material_personalizado.id",
            ondelete="RESTRICT",
            name="fk_acesso_material_personalizado_id",
        ),
        nullable=False,
    )
    # Sem índice adicional: a UniqueConstraint composta já cobre buscas por
    # material_personalizado_id; nenhum endpoint filtra por aluno_id isolado.
    aluno_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("aluno.id", ondelete="RESTRICT", name="fk_acesso_aluno_id"),
        nullable=False,
    )
    # Preenchidos pela lógica de negócio no primeiro/sucessivos PUT, nunca nulos depois que
    # a linha existe; sem server_default porque quem grava é a aplicação, não o schema.
    data_primeiro_acesso: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_ultimo_acesso: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tempo_total_leitura: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    quantidade_acessos: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Numeric em vez de Float: status_leitura depende de limites exatos (0% e 100%)
    # e float acumularia erro, sem nunca fechar em "CONCLUIDO".
    porcentagem_leitura: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, server_default="0"
    )
    download_realizado: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # Derivado no servidor a partir de porcentagem_leitura;
    # maior valor "NAO_INICIADO"/"EM_ANDAMENTO" (12 caracteres).
    status_leitura: Mapped[str] = mapped_column(String(20), nullable=False)

    material_personalizado: Mapped["MaterialPersonalizado"] = relationship(back_populates="acesso")
    aluno: Mapped["Aluno"] = relationship(back_populates="acessos")
