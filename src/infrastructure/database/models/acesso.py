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
    """Histórico de leitura de um Material Personalizado (Documento 2, §4.1).

    A linha só passa a existir no primeiro PUT .../acesso (Documento 3, §4.7) —
    não há criação antecipada ao gerar o Material Personalizado.
    """

    __tablename__ = "acesso"
    __table_args__ = (
        # Chave natural do registro (Documento 3, §4.7): material_personalizado_id
        # (path) + aluno_id (corpo). A cardinalidade "1:1 com Material
        # Personalizado" descrita no Documento 2 §4.1 é, na prática, garantida
        # indiretamente — cada Material Personalizado só é acessível pelo aluno
        # do Processamento que o originou — mas a constraint física que o
        # Documento 4 §8 define é esta, composta, não uma UNIQUE de coluna única
        # em material_personalizado_id.
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
    # Sem índice simples adicional: a UniqueConstraint composta acima já cobre
    # buscas por material_personalizado_id (coluna à esquerda do índice); não há
    # endpoint que filtre acesso por aluno_id isolado (Documento 3, §4.7), então
    # um índice dedicado a essa coluna não teria justificativa de uso.
    aluno_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("aluno.id", ondelete="RESTRICT", name="fk_acesso_aluno_id"),
        nullable=False,
    )
    # Preenchidos explicitamente pela lógica de negócio no primeiro/nos
    # sucessivos PUT — nunca nulos depois que a linha existe, mas sem
    # server_default: quem primeiro os grava é a Fase 3+, não o schema.
    data_primeiro_acesso: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_ultimo_acesso: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tempo_total_leitura: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    quantidade_acessos: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Numeric em vez de Float: porcentagem_leitura decide status_leitura em
    # limites exatos (0% e 100%, Documento 3 §4.7); Float é ponto flutuante
    # binário e arredondamentos acumulados ao longo de vários PUTs poderiam
    # deixar o valor a um épsilon de 1.0 sem nunca fechar em "CONCLUIDO".
    # Numeric(5, 4) representa exatamente frações entre 0 e 1 com quatro casas.
    porcentagem_leitura: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, server_default="0"
    )
    download_realizado: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # Derivado no servidor a partir de porcentagem_leitura (Documento 3, §4.7);
    # maior valor "NAO_INICIADO"/"EM_ANDAMENTO" (12 caracteres).
    status_leitura: Mapped[str] = mapped_column(String(20), nullable=False)

    material_personalizado: Mapped["MaterialPersonalizado"] = relationship(back_populates="acesso")
    aluno: Mapped["Aluno"] = relationship(back_populates="acessos")
