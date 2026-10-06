"""household stripe billing fields

Revision ID: 8f2b6a1d4c90
Revises: c1a2f5e9b3d7
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8f2b6a1d4c90'
down_revision: Union[str, None] = '1437ff0a5a1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('household', sa.Column('stripe_customer_id', sa.String(length=255), nullable=True))
    op.add_column('household', sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True))
    op.add_column('household', sa.Column('subscription_status', sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('household', 'subscription_status')
    op.drop_column('household', 'stripe_subscription_id')
    op.drop_column('household', 'stripe_customer_id')
