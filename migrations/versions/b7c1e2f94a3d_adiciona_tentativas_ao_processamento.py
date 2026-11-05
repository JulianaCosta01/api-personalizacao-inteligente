"""adiciona tentativas ao processamento

Revision ID: b7c1e2f94a3d
Revises: 4d5b6ae168df
Create Date: 2026-10-14 15:00:00.000000

Contador de reivindicações do Worker. NOT NULL com default 0, compatível com o código anterior.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c1e2f94a3d"
down_revision: str | Sequence[str] | None = "4d5b6ae168df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "processamento",
        sa.Column("tentativas", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("processamento", "tentativas")
