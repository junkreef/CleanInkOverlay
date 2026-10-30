"""ガチルール: the teams' points ('Np' under the count on the judge screen, on the scoreboard's WIN! / LOSE... rows)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('matches') as b:
        b.add_column(sa.Column('my_team_points', sa.Integer()))
        b.add_column(sa.Column('enemy_team_points', sa.Integer()))


def downgrade():
    with op.batch_alter_table('matches') as b:
        b.drop_column('enemy_team_points')
        b.drop_column('my_team_points')
