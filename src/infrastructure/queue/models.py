from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import Base


class MensagemFila(Base):
    """Fila de publicação de Processamentos, persistida em tabela própria.

    Não faz parte das sete entidades do DER (Documento 2); é um detalhe do
    adaptador concreto de IQueuePort, consumido pelo Worker.
    """

    __tablename__ = "fila_processamento"
    __table_args__ = (
        UniqueConstraint("processamento_id", name="uq_fila_processamento_processamento_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    processamento_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "processamento.id",
            ondelete="RESTRICT",
            name="fk_fila_processamento_processamento_id",
        ),
        nullable=False,
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
