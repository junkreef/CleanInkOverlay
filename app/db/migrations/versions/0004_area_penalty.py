"""ガチエリア: both teams' penalty once per second

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('timeline') as b:
        b.add_column(sa.Column('my_penalty', sa.Integer()))
        b.add_column(sa.Column('enemy_penalty', sa.Integer()))


def downgrade():
    with op.batch_alter_table('timeline') as b:
        for c in ('enemy_penalty', 'my_penalty'):
            b.drop_column(c)
