"""adiciona disponivel_em ao processamento

Revision ID: c3d8f1a07b52
Revises: b7c1e2f94a3d
Create Date: 2026-10-14 18:00:00.000000

A partir de quando um job devolvido à fila pode ser reivindicado de novo. Nulo = imediato.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d8f1a07b52"
down_revision: str | Sequence[str] | None = "b7c1e2f94a3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "processamento",
        sa.Column("disponivel_em", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("processamento", "disponivel_em")
