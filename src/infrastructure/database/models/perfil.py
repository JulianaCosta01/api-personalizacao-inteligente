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


class PerfilAprendizagem(Base):
    """Resultado do questionário Felder-Silverman.

    Relação 1:N com Aluno: cada aplicação do questionário cria um novo registro,
    preservando o histórico; não há endpoint de atualização.
    """

    __tablename__ = "perfil"
    __table_args__ = (Index("ix_perfil_aluno_id", "aluno_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    aluno_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("aluno.id", ondelete="RESTRICT", name="fk_perfil_aluno_id"),
        nullable=False,
    )
    # As quatro dimensões do Felder-Silverman: pares curtos (ex. "Ativo"/"Reflexivo",
    # "Sequencial"/"Global"); 20 dá folga sem exigir CHECK (ver nota em Aluno.grupo_experimental).
    estilo_processamento: Mapped[str] = mapped_column(String(20), nullable=False)
    percepcao: Mapped[str] = mapped_column(String(20), nullable=False)
    entrada: Mapped[str] = mapped_column(String(20), nullable=False)
    compreensao: Mapped[str] = mapped_column(String(20), nullable=False)
    # Texto gerado pelo Gemini de forma síncrona; nulo se a chamada falhar ou
    # estourar o tempo-limite, não bloqueia a criação do perfil.
    descricao_llm: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_atualizacao: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    aluno: Mapped["Aluno"] = relationship(back_populates="perfis")
    processamentos: Mapped[list["Processamento"]] = relationship(back_populates="perfil")
