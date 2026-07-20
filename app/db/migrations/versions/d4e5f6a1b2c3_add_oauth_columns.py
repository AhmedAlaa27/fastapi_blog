"""add oauth columns

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-07-20 16:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('auth_provider', sa.String(length=20), server_default='local', nullable=False),
    )
    op.add_column('users', sa.Column('oauth_sub', sa.String(length=255), nullable=True))
    op.alter_column(
        'users',
        'password_hash',
        existing_type=sa.VARCHAR(length=200),
        nullable=True,
    )
    op.create_unique_constraint('uq_users_oauth_sub', 'users', ['oauth_sub'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_users_oauth_sub', 'users', type_='unique')
    op.alter_column(
        'users',
        'password_hash',
        existing_type=sa.VARCHAR(length=200),
        nullable=False,
    )
    op.drop_column('users', 'oauth_sub')
    op.drop_column('users', 'auth_provider')
