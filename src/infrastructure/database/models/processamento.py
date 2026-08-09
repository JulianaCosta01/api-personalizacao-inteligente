from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.database.base import Base

if TYPE_CHECKING:
    from infrastructure.database.models.aluno import Aluno
    from infrastructure.database.models.log import LogInteracao
    from infrastructure.database.models.material import MaterialDidatico
    from infrastructure.database.models.material_personalizado import MaterialPersonalizado
    from infrastructure.database.models.perfil import PerfilAprendizagem

# Conjunto fechado de estados da máquina de estados (Documento 3, §14). Vive aqui
# porque é a própria constraint do banco quem o expressa (CHECK) — o vocabulário
# de domínio (enum Python) chega no módulo de Processamento na Fase 3.
ESTADOS_PROCESSAMENTO = ("pendente", "em_processamento", "concluido", "erro")


class Processamento(Base):
    """Solicitação de personalização de um material para um aluno (Documento 2, §4.1).

    Entidade central do fluxo assíncrono: referencia um snapshot do Perfil de
    Aprendizagem vigente no momento da solicitação (Documento 3, §4.4) e evolui
    por uma máquina de estados de quatro estados terminais/não-terminais
    (Documento 3, §14).
    """

    __tablename__ = "processamento"
    __table_args__ = (
        Index("ix_processamento_aluno_id", "aluno_id"),
        Index("ix_processamento_material_didatico_id", "material_didatico_id"),
        Index("ix_processamento_perfil_id", "perfil_id"),
        Index("ix_processamento_status", "status"),
        Index("ix_processamento_data_criacao", "data_criacao"),
        # O nome final vira "ck_processamento_status_valido" — a convenção de
        # Base.metadata (ck_%(table_name)s_%(constraint_name)s) sempre reaplica
        # o prefixo sobre o `name` de um CheckConstraint, diferente de
        # ForeignKey/UniqueConstraint, que respeitam o nome dado ao pé da letra.
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
    # Preenchido pelo Worker ao iniciar a execução (Documento 3, §4.4); nulo até lá.
    modelo_ia: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_criacao: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # inicio/fim marcam transições de estado futuras (Worker) — não são "criação
    # de linha", por isso não recebem server_default: quem os preenche é a
    # lógica de negócio da Fase 3+, no momento exato da transição.
    inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fim: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Mensagem de exceção/stack: tamanho imprevisível, Text para não arriscar
    # truncar contexto de diagnóstico.
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)

    aluno: Mapped["Aluno"] = relationship(back_populates="processamentos")
    material_didatico: Mapped["MaterialDidatico"] = relationship(back_populates="processamentos")
    perfil: Mapped["PerfilAprendizagem"] = relationship(back_populates="processamentos")
    logs: Mapped[list["LogInteracao"]] = relationship(back_populates="processamento")
    material_personalizado: Mapped["MaterialPersonalizado | None"] = relationship(
        back_populates="processamento", uselist=False
    )
