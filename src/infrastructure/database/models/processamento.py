from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.database.base import Base

if TYPE_CHECKING:
    from infrastructure.database.models.aluno import Aluno
    from infrastructure.database.models.log import LogInteracao
    from infrastructure.database.models.material import MaterialDidatico
    from infrastructure.database.models.material_personalizado import MaterialPersonalizado
    from infrastructure.database.models.perfil import PerfilAprendizagem

# Conjunto fechado de estados da máquina de estados; vive aqui porque
# é a própria constraint do banco (CHECK) que o expressa: o enum Python fica no Domínio.
ESTADOS_PROCESSAMENTO = ("pendente", "em_processamento", "concluido", "erro")


class Processamento(Base):
    """Solicitação de personalização de um material para um aluno.

    Entidade central do fluxo assíncrono: referencia um snapshot do Perfil de
    Aprendizagem vigente no momento da solicitação e evolui
    por uma máquina de estados de quatro estados terminais/não-terminais.
    """

    __tablename__ = "processamento"
    __table_args__ = (
        Index("ix_processamento_aluno_id", "aluno_id"),
        Index("ix_processamento_material_didatico_id", "material_didatico_id"),
        Index("ix_processamento_perfil_id", "perfil_id"),
        Index("ix_processamento_status", "status"),
        Index("ix_processamento_data_criacao", "data_criacao"),
        # Nome final vira "ck_processamento_status_valido": a convenção de Base.metadata
        # reaplica o prefixo sobre CheckConstraint.name, diferente de FK/UniqueConstraint.
        CheckConstraint(f"status IN {ESTADOS_PROCESSAMENTO}", name="status_valido"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    aluno_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("aluno.id", ondelete="RESTRICT", name="fk_processamento_aluno_id"),
        nullable=False,
    )
    material_didatico_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "material.id", ondelete="RESTRICT", name="fk_processamento_material_didatico_id"
        ),
        nullable=False,
    )
    perfil_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("perfil.id", ondelete="RESTRICT", name="fk_processamento_perfil_id"),
        nullable=False,
    )
    # Maior valor é "em_processamento" (17 caracteres); o conjunto fechado é
    # garantido pelo CheckConstraint acima, não apenas pelo tamanho da coluna.
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # Preenchido pelo Worker ao iniciar a execução; nulo até lá.
    modelo_ia: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_criacao: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # inicio/fim marcam transições de estado (Worker), não a criação da linha; sem
    # server_default porque quem preenche é a lógica de negócio, no momento da transição.
    inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fim: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Mensagem de exceção/stack: tamanho imprevisível, Text para não arriscar
    # truncar contexto de diagnóstico.
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    tentativas: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Espera antes da próxima reivindicação (falha transitória do provedor); nulo = disponível.
    disponivel_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    aluno: Mapped["Aluno"] = relationship(back_populates="processamentos")
    material_didatico: Mapped["MaterialDidatico"] = relationship(back_populates="processamentos")
    perfil: Mapped["PerfilAprendizagem"] = relationship(back_populates="processamentos")
    logs: Mapped[list["LogInteracao"]] = relationship(back_populates="processamento")
    material_personalizado: Mapped["MaterialPersonalizado | None"] = relationship(
        back_populates="processamento", uselist=False
    )
