"""transaction + category rule income flag

Revision ID: b7e4c2a9d1f3
Revises: 8f2b6a1d4c90
Create Date: 2026-09-18 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7e4c2a9d1f3'
down_revision: Union[str, None] = '8f2b6a1d4c90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Backfill from the sign so every existing row classifies exactly as it
    # did before (amount >= 0 was the old definition of income); refunds get
    # reclassified by hand afterwards.
    op.add_column('transaction', sa.Column('income', sa.Boolean(), nullable=True))
    op.execute("UPDATE `transaction` SET income = (amount >= 0)")
    op.alter_column('transaction', 'income', existing_type=sa.Boolean(), nullable=False)

    # Existing rules predate the flag — only rules filing into the Income
    # category describe an income source.
    op.add_column(
        'categoryrule',
        sa.Column('income', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE categoryrule SET income = 1 WHERE LOWER(category) = 'income'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('categoryrule', 'income')
    op.drop_column('transaction', 'income')
