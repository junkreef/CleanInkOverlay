"""ガチヤグラ / ガチホコ: the objective's track once per second (position, who holds it, each team's best); ガチエリア: both
counts once per second; overtime

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('timeline') as b:
        b.add_column(sa.Column('obj_pos', sa.REAL()))
        b.add_column(sa.Column('obj_holder', sa.Text()))
        b.add_column(sa.Column('my_best', sa.REAL()))
        b.add_column(sa.Column('enemy_best', sa.REAL()))
        b.add_column(sa.Column('my_count', sa.Integer()))
        b.add_column(sa.Column('enemy_count', sa.Integer()))
        b.add_column(sa.Column('overtime', sa.Integer()))


def downgrade():
    with op.batch_alter_table('timeline') as b:
        for c in ('overtime', 'enemy_count', 'my_count', 'enemy_best', 'my_best', 'obj_holder', 'obj_pos'):
            b.drop_column(c)
