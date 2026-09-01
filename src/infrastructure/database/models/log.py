from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.database.base import Base

if TYPE_CHECKING:
    from infrastructure.database.models.aluno import Aluno
    from infrastructure.database.models.processamento import Processamento


class LogInteracao(Base):
    """Auditoria de ações do aluno (Documento 2, §4.1; catálogo de eventos no Documento 3, §10)."""

    __tablename__ = "log"
    __table_args__ = (
        Index("ix_log_aluno_id", "aluno_id"),
        Index("ix_log_processamento_id", "processamento_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    aluno_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("aluno.id", ondelete="RESTRICT", name="fk_log_aluno_id"),
        nullable=False,
    )
    # Opcional (Documento 3, §4.6): existem ações do aluno não vinculadas a um
    # processamento específico (ex.: acesso à disciplina no Moodle).
    processamento_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("processamento.id", ondelete="RESTRICT", name="fk_log_processamento_id"),
        nullable=True,
    )
    # Identificador de evento do catálogo (Documento 3 §10); 100 dá folga real sobre o
    # maior nome de evento, sem virar texto livre longo — esse é o papel de descricao.
    acao: Mapped[str] = mapped_column(String(100), nullable=False)
    # Texto livre opcional (Documento 3, §4.6).
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Sempre gerado no servidor, nunca aceito do cliente (Documento 3, §4.6).
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    aluno: Mapped["Aluno"] = relationship(back_populates="logs")
    processamento: Mapped["Processamento | None"] = relationship(back_populates="logs")
