"""baseline: the schema as of the SQLAlchemy move (2026-09-17), matching app/db/models.py at that time

Revision ID: 0001
Revises:
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('matches',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('started_at', sa.Text(), nullable=False),
        sa.Column('ended_at', sa.Text()),
        sa.Column('mode', sa.Text()),
        sa.Column('rule', sa.Text()),
        sa.Column('stage', sa.Text()),
        sa.Column('result', sa.Text()),
        sa.Column('my_pct', sa.REAL()),
        sa.Column('enemy_pct', sa.REAL()),
        sa.Column('my_count', sa.Integer()),
        sa.Column('enemy_count', sa.Integer()),
        sa.Column('knockout', sa.Integer()),
        sa.Column('duration_s', sa.REAL()),
        sa.Column('source', sa.Text()),
        sa.Column('rule_image', sa.Text()),
        sa.Column('result_image', sa.Text()),
        sa.Column('medal_image', sa.Text()),
        sa.Column('raw_json', sa.Text()),
        sa.Column('notes', sa.Text()),
        sa.CheckConstraint("result IN ('win', 'lose', 'draw')"))
    op.create_table('match_players',
        sa.Column('match_id', sa.Integer(), sa.ForeignKey('matches.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('slot', sa.Integer(), primary_key=True),
        sa.Column('team', sa.Text(), nullable=False),
        sa.Column('is_self', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('weapon', sa.Text()),
        sa.Column('weapon_score', sa.REAL()),
        sa.Column('weapon_conf', sa.REAL()),
        sa.Column('points', sa.Integer()),
        sa.Column('kills_assists', sa.Integer()),
        sa.Column('deaths', sa.Integer()),
        sa.Column('specials', sa.Integer()),
        sa.Column('result_row', sa.Integer()),
        sa.Column('link_score', sa.REAL()),
        sa.CheckConstraint("team IN ('ally', 'enemy')"))
    op.create_table('events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('match_id', sa.Integer(), sa.ForeignKey('matches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('t_ms', sa.Integer(), nullable=False),
        sa.Column('clock', sa.Text()),
        sa.Column('type', sa.Text(), nullable=False),
        sa.Column('slot', sa.Integer()),
        sa.Column('target_slot', sa.Integer()),
        sa.Column('weapon', sa.Text()),
        sa.Column('source', sa.Text()),
        sa.Column('confidence', sa.REAL()),
        sa.Column('duration_ms', sa.Integer()),
        sa.CheckConstraint("type IN ('death', 'kill', 'killed_by', 'special', 'special_ready')"))
    op.create_index('events_match', 'events', ['match_id', 't_ms'])
    op.create_table('timeline',
        sa.Column('match_id', sa.Integer(), sa.ForeignKey('matches.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('t_s', sa.Integer(), primary_key=True),
        sa.Column('points', sa.Integer()),
        sa.Column('gauge', sa.REAL()),
        sa.Column('ready', sa.Integer()))
    op.create_table('medals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('match_id', sa.Integer(), sa.ForeignKey('matches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('rank', sa.Text()),
        sa.Column('position', sa.Integer()),
        sa.Column('sig_id', sa.Text()))
    op.create_table('weapons',
        sa.Column('name', sa.Text(), primary_key=True),
        sa.Column('class', sa.Text()))


def downgrade():
    for t in ('medals', 'timeline', 'events', 'match_players', 'weapons', 'matches'):
        op.drop_table(t)
