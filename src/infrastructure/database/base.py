from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Convenção explícita de nomes (Alembic recomenda isso para autogenerate produzir
# nomes estáveis e previsíveis, em vez dos nomes que o Postgres geraria sozinho,
# como "processamento_status_check1" — que mudam de projeto para projeto e
# dificultam ler uma migration ou uma mensagem de erro de IntegrityError).
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base declarativa das entidades mapeadas (Mapped[]/mapped_column)."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
