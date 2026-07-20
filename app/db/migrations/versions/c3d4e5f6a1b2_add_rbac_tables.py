"""add rbac tables

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-07-20 16:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a1b2'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISSIONS = ['posts:create', 'posts:update', 'posts:delete']
ROLE_PERMISSIONS = {
    'admin': ['posts:create', 'posts:update', 'posts:delete'],
    'author': ['posts:create'],
}


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'permissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_permissions_id'), 'permissions', ['id'], unique=False)
    op.create_table(
        'roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_roles_id'), 'roles', ['id'], unique=False)
    op.create_table(
        'role_permissions',
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.Column('permission_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
        sa.PrimaryKeyConstraint('role_id', 'permission_id'),
    )
    op.create_table(
        'user_roles',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('user_id', 'role_id'),
    )

    bind = op.get_bind()

    permissions_table = sa.table(
        'permissions', sa.column('id', sa.Integer), sa.column('name', sa.String)
    )
    roles_table = sa.table(
        'roles', sa.column('id', sa.Integer), sa.column('name', sa.String)
    )
    role_permissions_table = sa.table(
        'role_permissions',
        sa.column('role_id', sa.Integer),
        sa.column('permission_id', sa.Integer),
    )
    user_roles_table = sa.table(
        'user_roles', sa.column('user_id', sa.Integer), sa.column('role_id', sa.Integer)
    )
    users_table = sa.table('users', sa.column('id', sa.Integer))

    permission_ids = {
        name: bind.execute(
            permissions_table.insert().values(name=name).returning(permissions_table.c.id)
        ).scalar_one()
        for name in PERMISSIONS
    }

    role_ids = {}
    for role_name, perm_names in ROLE_PERMISSIONS.items():
        role_id = bind.execute(
            roles_table.insert().values(name=role_name).returning(roles_table.c.id)
        ).scalar_one()
        role_ids[role_name] = role_id
        bind.execute(
            role_permissions_table.insert(),
            [
                {'role_id': role_id, 'permission_id': permission_ids[perm_name]}
                for perm_name in perm_names
            ],
        )

    author_role_id = role_ids['author']
    existing_user_ids = bind.execute(sa.select(users_table.c.id)).scalars().all()
    if existing_user_ids:
        bind.execute(
            user_roles_table.insert(),
            [
                {'user_id': user_id, 'role_id': author_role_id}
                for user_id in existing_user_ids
            ],
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('user_roles')
    op.drop_table('role_permissions')
    op.drop_index(op.f('ix_roles_id'), table_name='roles')
    op.drop_table('roles')
    op.drop_index(op.f('ix_permissions_id'), table_name='permissions')
    op.drop_table('permissions')
