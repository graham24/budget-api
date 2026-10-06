"""add importerrorlog table

Revision ID: c1a2f5e9b3d7
Revises: 900a32770114
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c1a2f5e9b3d7'
down_revision: Union[str, None] = '900a32770114'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'importerrorlog',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('household_id', sa.Integer(), nullable=False),
        sa.Column('message', sa.String(length=1024), nullable=False),
        sa.Column('created', sa.DateTime(), nullable=False),
        sa.Column('modified', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['household_id'], ['household.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('importerrorlog')
