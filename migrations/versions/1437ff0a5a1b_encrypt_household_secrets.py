"""encrypt household secrets

Revision ID: 1437ff0a5a1b
Revises: c1a2f5e9b3d7
Create Date: 2026-08-10 09:58:32.471991

Widens household.anthropic_api_key / simplefin_access_url from
VARCHAR(255) to TEXT (Fernet ciphertext runs past 255 chars for a
SimpleFin access URL) and encrypts the existing plaintext values in
place. Reads/writes go through raw SQL rather than the ORM model, since
the model's EncryptedString column type would try to decrypt
still-plaintext rows before this migration has run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '1437ff0a5a1b'
down_revision: Union[str, None] = 'c1a2f5e9b3d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from crypto_utils import encrypt

    op.alter_column('household', 'anthropic_api_key',
               existing_type=mysql.VARCHAR(length=255),
               type_=sa.Text(),
               existing_nullable=True)
    op.alter_column('household', 'simplefin_access_url',
               existing_type=mysql.VARCHAR(length=255),
               type_=sa.Text(),
               existing_nullable=True)

    bind = op.get_bind()
    rows = bind.execute(
        text("SELECT id, anthropic_api_key, simplefin_access_url FROM household")
    ).fetchall()
    for row in rows:
        updates = {}
        if row.anthropic_api_key is not None:
            updates["anthropic_api_key"] = encrypt(row.anthropic_api_key)
        if row.simplefin_access_url is not None:
            updates["simplefin_access_url"] = encrypt(row.simplefin_access_url)
        if updates:
            set_clause = ", ".join(f"{col} = :{col}" for col in updates)
            bind.execute(
                text(f"UPDATE household SET {set_clause} WHERE id = :id"),
                {**updates, "id": row.id},
            )


def downgrade() -> None:
    from crypto_utils import decrypt

    bind = op.get_bind()
    rows = bind.execute(
        text("SELECT id, anthropic_api_key, simplefin_access_url FROM household")
    ).fetchall()
    for row in rows:
        updates = {}
        if row.anthropic_api_key is not None:
            updates["anthropic_api_key"] = decrypt(row.anthropic_api_key)
        if row.simplefin_access_url is not None:
            updates["simplefin_access_url"] = decrypt(row.simplefin_access_url)
        if updates:
            set_clause = ", ".join(f"{col} = :{col}" for col in updates)
            bind.execute(
                text(f"UPDATE household SET {set_clause} WHERE id = :id"),
                {**updates, "id": row.id},
            )

    op.alter_column('household', 'simplefin_access_url',
               existing_type=sa.Text(),
               type_=mysql.VARCHAR(length=255),
               existing_nullable=True)
    op.alter_column('household', 'anthropic_api_key',
               existing_type=sa.Text(),
               type_=mysql.VARCHAR(length=255),
               existing_nullable=True)
