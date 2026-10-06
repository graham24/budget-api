"""simplefinaccount unique constraint on simplefin_account_id

Revision ID: 900a32770114
Revises: da659e51bafd
Create Date: 2026-08-06 13:10:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '900a32770114'
down_revision: Union[str, None] = 'da659e51bafd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Pre-existing duplicate simplefin_account_id rows (from re-claims before
    # this constraint existed) would violate the unique index below — keep
    # only the most recently created row per simplefin_account_id.
    op.execute(
        """
        DELETE sfa1 FROM simplefinaccount sfa1
        JOIN simplefinaccount sfa2
          ON sfa1.simplefin_account_id = sfa2.simplefin_account_id
         AND sfa1.id < sfa2.id
        """
    )
    op.create_unique_constraint(
        'uq_simplefinaccount_simplefin_account_id',
        'simplefinaccount', ['simplefin_account_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_simplefinaccount_simplefin_account_id', 'simplefinaccount', type_='unique')
