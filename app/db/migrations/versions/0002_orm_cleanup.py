"""ORM cleanup: every table is rebuilt in the form SQLAlchemy describes it (so that `alembic revision --autogenerate`
sees no phantom differences on files that work/db.py created by hand), medals gets an id primary key (the ORM
needs one), and the stat views go (app/db/queries.py computes them). Along the way DBs from before 2026-09-15
lose match_players.name / name_sig_id and get the events CHECK that allows 'special_ready'.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

VIEWS = ('my_matches', 'weapon_stats', 'stage_stats', 'enemy_weapon_stats', 'medal_stats', 'my_timeline')


def fk_match():
    return sa.Column('match_id', sa.Integer(), sa.ForeignKey('matches.id', ondelete='CASCADE'), nullable=False)


def canonical_tables(medal_id=True):
    """table -> (columns, constraints) as the models declare them at this revision (frozen copy, on purpose)"""
    return {
        'matches': ([sa.Column('id', sa.Integer(), primary_key=True),
                     sa.Column('started_at', sa.Text(), nullable=False), sa.Column('ended_at', sa.Text()),
                     sa.Column('mode', sa.Text()), sa.Column('rule', sa.Text()), sa.Column('stage', sa.Text()), sa.Column('result', sa.Text()),
                     sa.Column('my_pct', sa.REAL()), sa.Column('enemy_pct', sa.REAL()),
                     sa.Column('my_count', sa.Integer()), sa.Column('enemy_count', sa.Integer()), sa.Column('knockout', sa.Integer()),
                     sa.Column('duration_s', sa.REAL()), sa.Column('source', sa.Text()),
                     sa.Column('rule_image', sa.Text()), sa.Column('result_image', sa.Text()), sa.Column('medal_image', sa.Text()),
                     sa.Column('raw_json', sa.Text()), sa.Column('notes', sa.Text())],
                    [sa.CheckConstraint("result IN ('win', 'lose', 'draw')")]),
        'match_players': ([sa.Column('match_id', sa.Integer(), sa.ForeignKey('matches.id', ondelete='CASCADE'), primary_key=True),
                           sa.Column('slot', sa.Integer(), primary_key=True),
                           sa.Column('team', sa.Text(), nullable=False), sa.Column('is_self', sa.Integer(), nullable=False, server_default='0'),
                           sa.Column('weapon', sa.Text()), sa.Column('weapon_score', sa.REAL()), sa.Column('weapon_conf', sa.REAL()),
                           sa.Column('points', sa.Integer()), sa.Column('kills_assists', sa.Integer()), sa.Column('deaths', sa.Integer()),
                           sa.Column('specials', sa.Integer()), sa.Column('result_row', sa.Integer()), sa.Column('link_score', sa.REAL())],
                          [sa.CheckConstraint("team IN ('ally', 'enemy')")]),
        'events': ([sa.Column('id', sa.Integer(), primary_key=True), fk_match(),
                    sa.Column('t_ms', sa.Integer(), nullable=False), sa.Column('clock', sa.Text()), sa.Column('type', sa.Text(), nullable=False),
                    sa.Column('slot', sa.Integer()), sa.Column('target_slot', sa.Integer()), sa.Column('weapon', sa.Text()),
                    sa.Column('source', sa.Text()), sa.Column('confidence', sa.REAL()), sa.Column('duration_ms', sa.Integer())],
                   [sa.CheckConstraint("type IN ('death', 'kill', 'killed_by', 'special', 'special_ready')")]),
        'timeline': ([sa.Column('match_id', sa.Integer(), sa.ForeignKey('matches.id', ondelete='CASCADE'), primary_key=True),
                      sa.Column('t_s', sa.Integer(), primary_key=True),
                      sa.Column('points', sa.Integer()), sa.Column('gauge', sa.REAL()), sa.Column('ready', sa.Integer())], []),
        'medals': (([sa.Column('id', sa.Integer(), primary_key=True)] if medal_id else []) +
                   [fk_match(), sa.Column('name', sa.Text(), nullable=False), sa.Column('rank', sa.Text()),
                    sa.Column('position', sa.Integer()), sa.Column('sig_id', sa.Text())], []),
        'weapons': ([sa.Column('name', sa.Text(), primary_key=True), sa.Column('class', sa.Text())], []),
    }


def rebuild(table, columns, constraints):
    """SQLite cannot ALTER constraints or primary keys: create the table anew, copy the columns both have (rowid order,
    so a fresh INTEGER PRIMARY KEY numbers rows in their old order), swap. Columns the old table lacks come out NULL.
    A table the old file does not have at all (timeline before 2026-09-17) is simply created."""
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        op.create_table(table, *columns, *constraints); return
    old = [c['name'] for c in insp.get_columns(table)]
    keep = [c.name for c in columns if c.name in old]
    op.create_table(f'{table}_new', *columns, *constraints)
    cols = ', '.join(f'"{c}"' for c in keep)
    op.execute(f'INSERT INTO {table}_new ({cols}) SELECT {cols} FROM {table} ORDER BY rowid')
    op.drop_table(table)
    op.rename_table(f'{table}_new', table)


def upgrade():
    for v in VIEWS:
        op.execute(f'DROP VIEW IF EXISTS {v}')
    op.execute('DROP INDEX IF EXISTS events_match')
    for table, (columns, constraints) in canonical_tables().items():
        rebuild(table, columns, constraints)
    op.create_index('events_match', 'events', ['match_id', 't_ms'])


def downgrade():
    columns, constraints = canonical_tables(medal_id=False)['medals']
    rebuild('medals', columns, constraints)
    for stmt in LEGACY_VIEWS.split(';'):
        if stmt.strip(): op.execute(stmt)


LEGACY_VIEWS = """
CREATE VIEW my_matches AS
  SELECT m.id, m.started_at, m.stage, m.mode, m.rule, m.result, m.my_pct, m.enemy_pct,
         p.weapon, p.points, p.kills_assists, p.deaths, p.specials
  FROM matches m JOIN match_players p ON p.match_id = m.id AND p.is_self = 1;
CREATE VIEW weapon_stats AS
  SELECT weapon, COUNT(*) AS games, SUM(result = 'win') AS wins,
         ROUND(100.0 * SUM(result = 'win') / COUNT(*), 1) AS win_pct,
         ROUND(AVG(kills_assists), 2) AS avg_ka, ROUND(AVG(deaths), 2) AS avg_d, ROUND(AVG(specials), 2) AS avg_sp,
         ROUND(AVG(points)) AS avg_points
  FROM my_matches GROUP BY weapon ORDER BY games DESC;
CREATE VIEW stage_stats AS
  SELECT stage, COUNT(*) AS games, SUM(result = 'win') AS wins,
         ROUND(100.0 * SUM(result = 'win') / COUNT(*), 1) AS win_pct,
         ROUND(AVG(kills_assists), 2) AS avg_ka, ROUND(AVG(deaths), 2) AS avg_d, ROUND(AVG(points)) AS avg_points
  FROM my_matches GROUP BY stage ORDER BY games DESC;
CREATE VIEW enemy_weapon_stats AS
  SELECT p.weapon, COUNT(*) AS seen, SUM(m.result = 'win') AS wins,
         ROUND(100.0 * SUM(m.result = 'win') / COUNT(*), 1) AS win_pct,
         (SELECT COUNT(*) FROM events e JOIN match_players k ON k.match_id = e.match_id AND k.slot = e.target_slot
          WHERE e.type = 'killed_by' AND k.weapon = p.weapon) AS killed_me,
         (SELECT COUNT(*) FROM events e JOIN match_players v ON v.match_id = e.match_id AND v.slot = e.target_slot
          WHERE e.type = 'kill' AND v.weapon = p.weapon) AS i_killed
  FROM match_players p JOIN matches m ON m.id = p.match_id
  WHERE p.team = 'enemy' AND p.weapon IS NOT NULL GROUP BY p.weapon ORDER BY seen DESC;
CREATE VIEW medal_stats AS
  SELECT name, rank, COUNT(*) AS n FROM medals GROUP BY name, rank ORDER BY n DESC;
CREATE VIEW my_timeline AS
  SELECT (e.t_ms / 30000) * 30 AS from_s, e.type, COUNT(*) AS n
  FROM events e JOIN match_players p ON p.match_id = e.match_id AND p.slot = e.slot AND p.is_self = 1
  WHERE e.type IN ('kill', 'killed_by', 'death') GROUP BY from_s, e.type ORDER BY from_s, e.type;
"""
