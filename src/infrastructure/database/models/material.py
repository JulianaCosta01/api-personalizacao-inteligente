from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.database.base import Base

if TYPE_CHECKING:
    from infrastructure.database.models.processamento import Processamento


class MaterialDidatico(Base):
    """Material-fonte em PDF fornecido pelo docente."""

    __tablename__ = "material"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    # Título de material didático: mesmo teto convencional usado em MaterialPersonalizado.titulo.
    titulo: Mapped[str] = mapped_column(String(255), nullable=False)
    # 255 é o limite de nome de componente em ext4/NTFS: alinhado ao próprio filesystem.
    nome_arquivo: Mapped[str] = mapped_column(String(255), nullable=False)
    # Hoje só PDF é aceito; 50 já comporta mime-types mais longos
    # caso o formato aceito seja estendido no futuro, sem exigir novo ALTER.
    tipo_arquivo: Mapped[str] = mapped_column(String(50), nullable=False)
    # Chave no Object Storage, nunca caminho de filesystem; 500 dá folga para
    # prefixos de bucket/pasta.
    caminho_storage: Mapped[str] = mapped_column(String(500), nullable=False)
    versao: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    data_upload: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    processamentos: Mapped[list["Processamento"]] = relationship(back_populates="material_didatico")
