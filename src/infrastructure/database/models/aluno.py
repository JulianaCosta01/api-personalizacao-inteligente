from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.database.base import Base

if TYPE_CHECKING:
    from infrastructure.database.models.acesso import AcessoMaterialPersonalizado
    from infrastructure.database.models.log import LogInteracao
    from infrastructure.database.models.perfil import PerfilAprendizagem
    from infrastructure.database.models.processamento import Processamento


class Aluno(Base):
    """Estudante do Moodle, sincronizado no primeiro contato do Plugin."""

    __tablename__ = "aluno"
    __table_args__ = (UniqueConstraint("matricula", name="uq_aluno_matricula"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    # nome de pessoa: 255 é o teto convencional do setor, com folga ampla sobre
    # qualquer nome real.
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    # RFC 5321 limita o endereço completo a 254 caracteres: teto técnico, não arbitrário.
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    # matrícula da UFMA é numérica curta (ex.: "2021045123"); 20 dá folga a
    # variações de formato sem abrir espaço demais.
    matricula: Mapped[str] = mapped_column(String(20), nullable=False)
    data_cadastro: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # "experimental"/"controle", imutável após criação. Validado no schema Pydantic;
    # CHECK no banco fica restrito a Processamento.status.
    grupo_experimental: Mapped[str] = mapped_column(String(20), nullable=False)

    perfis: Mapped[list["PerfilAprendizagem"]] = relationship(back_populates="aluno")
    processamentos: Mapped[list["Processamento"]] = relationship(back_populates="aluno")
    logs: Mapped[list["LogInteracao"]] = relationship(back_populates="aluno")
    acessos: Mapped[list["AcessoMaterialPersonalizado"]] = relationship(back_populates="aluno")
