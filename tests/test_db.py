"""DB layer: fresh files, migration of pre-ORM files, the Store's read/write API, model <-> migration parity.
    uv run pytest
"""
import json, os, sqlite3, sys
import pytest
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path: sys.path.insert(0, ROOT)
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.db import Base, make_engine, upgrade, current_revision, head_revision, migrate
from app.store import Store

# the schema work/db.py created on 2026-09-13 (before medal_image / medals.position / sig_id were added by ALTER,
# with player-name columns, the events CHECK without special_ready, no timeline table yet, and the stat views)
LEGACY_SCHEMA = """
CREATE TABLE matches (id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT, mode TEXT, rule TEXT, stage TEXT,
  result TEXT CHECK (result IN ('win', 'lose', 'draw')), my_pct REAL, enemy_pct REAL, my_count INTEGER, enemy_count INTEGER,
  knockout INTEGER, duration_s REAL, source TEXT, rule_image TEXT, result_image TEXT, raw_json TEXT, notes TEXT);
CREATE TABLE match_players (match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE, slot INTEGER NOT NULL,
  team TEXT NOT NULL CHECK (team IN ('ally', 'enemy')), is_self INTEGER NOT NULL DEFAULT 0, name TEXT, name_sig_id TEXT, weapon TEXT,
  weapon_score REAL, weapon_conf REAL, points INTEGER, kills_assists INTEGER, deaths INTEGER, specials INTEGER, result_row INTEGER,
  link_score REAL, PRIMARY KEY (match_id, slot));
CREATE TABLE events (id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE, t_ms INTEGER NOT NULL,
  clock TEXT, type TEXT NOT NULL CHECK (type IN ('death', 'kill', 'killed_by', 'special')), slot INTEGER, target_slot INTEGER,
  weapon TEXT, source TEXT, confidence REAL, duration_ms INTEGER);
CREATE INDEX events_match ON events(match_id, t_ms);
CREATE TABLE medals (match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE, name TEXT NOT NULL, rank TEXT);
CREATE TABLE weapons (name TEXT PRIMARY KEY, class TEXT);
CREATE VIEW my_matches AS SELECT m.id, m.result, p.weapon, p.points, p.kills_assists, p.deaths, p.specials
  FROM matches m JOIN match_players p ON p.match_id = m.id AND p.is_self = 1;
CREATE VIEW weapon_stats AS SELECT weapon, COUNT(*) AS games FROM my_matches GROUP BY weapon;
"""


def sample_match(started='2026-09-16T20:00:00', result='win'):
    match = dict(started_at=started, mode='レギュラーマッチ', rule='ナワバリバトル', stage='ゴンズイ地区', result=result, my_pct=55.5, enemy_pct=44.5,
                 duration_s=183.0, source='test', raw_json=json.dumps({'stage_id': 's_test1'}))
    players = [dict(slot=i, team='ally' if i < 4 else 'enemy', is_self=int(i == 1), weapon='わかばシューター' if i != 5 else 'スプラローラー',
                    points=1000 + i, kills_assists=i, deaths=8 - i, specials=2) for i in range(8)]
    events = [dict(t_ms=1000, type='killed_by', slot=1, target_slot=5, source='bubble'), dict(t_ms=40000, type='kill', slot=1, target_slot=5, source='killfeed'),
              dict(t_ms=70000, type='death', slot=3, source='hud'), dict(t_ms=90000, type='special_ready', slot=1, source='hud')]
    medals = [dict(name='ナワバリ王', rank='gold', position=0), dict(sig_id='m_abcd', rank='silver', position=1)]
    timeline = [dict(t_s=0, points=0, gauge=0.0, ready=0), dict(t_s=1, points=12, gauge=0.05, ready=0)]
    return match, players, events, medals, timeline


def schema_diff(db_path):
    engine = make_engine(db_path)
    try:
        with engine.connect() as con:
            return compare_metadata(MigrationContext.configure(con), Base.metadata)
    finally:
        engine.dispose()


def table_sql(db_path, name):
    con = sqlite3.connect(db_path)
    try: return con.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()[0]
    finally: con.close()


def test_fresh_db_is_created_at_head_and_matches_models(tmp_path):
    db = str(tmp_path / 'new.db')
    assert upgrade(db) == (None, head_revision())
    assert current_revision(db) == head_revision()
    assert schema_diff(db) == []


def test_legacy_db_is_backed_up_stamped_and_migrated(tmp_path):
    db = str(tmp_path / 'old.db')
    con = sqlite3.connect(db); con.executescript(LEGACY_SCHEMA)
    con.execute("INSERT INTO matches (id, started_at, result) VALUES (1, '2026-09-13T10:00:00', 'win')")
    con.execute("INSERT INTO match_players (match_id, slot, team, is_self, name, weapon) VALUES (1, 0, 'ally', 1, 'ひらパー', 'わかばシューター')")
    con.execute("INSERT INTO events (match_id, t_ms, type, slot) VALUES (1, 5000, 'death', 0)")
    con.execute("INSERT INTO medals (match_id, name, rank) VALUES (1, 'ナワバリ王', 'gold'), (1, 'm_x', 'silver')")
    con.commit(); con.close()
    assert migrate.is_legacy(db) and current_revision(db) is None

    logs = []
    assert upgrade(db, log=logs.append) == ('0001', head_revision())
    backups = [p for p in os.listdir(tmp_path) if p.startswith('old.db.bak-')]
    assert len(backups) == 1 and any(backups[0] in l for l in logs)
    assert schema_diff(db) == []                                   # the migrated file is exactly what the models describe
    con = sqlite3.connect(db)
    assert con.execute("SELECT name FROM sqlite_master WHERE type = 'view'").fetchall() == []
    cols = {r[1] for r in con.execute('PRAGMA table_info(match_players)')}
    assert 'name' not in cols and 'name_sig_id' not in cols and 'weapon' in cols
    assert 'special_ready' in table_sql(db, 'events')
    assert con.execute('SELECT id, match_id, name, rank, position, sig_id FROM medals ORDER BY id').fetchall() == [(1, 1, 'ナワバリ王', 'gold', None, None), (2, 1, 'm_x', 'silver', None, None)]
    assert con.execute('SELECT match_id, slot, weapon FROM match_players').fetchall() == [(1, 0, 'わかばシューター')]
    assert con.execute('SELECT t_ms, type FROM events').fetchall() == [(5000, 'death')]
    con.close()
    # a second open is a no-op (no new backup, no new revision)
    assert upgrade(db) == (head_revision(), head_revision())
    assert len([p for p in os.listdir(tmp_path) if p.startswith('old.db.bak-')]) == 1
    # and the store can insert into it right away, including the event type the old CHECK refused
    s = Store(db_path=db); mid = s.insert_match(*sample_match()); assert mid == 2
    assert [e['type'] for e in s.get_match(2)['events']] == ['killed_by', 'kill', 'death', 'special_ready']
    s.close()


def test_store_roundtrip_and_stats(tmp_path):
    s = Store(db_path=str(tmp_path / 'store.db'))
    saved = []; s.events.subscribe('match_saved', saved.append)
    mid = s.insert_match(*sample_match()); mid2 = s.insert_match(*sample_match('2026-09-16T21:00:00', 'lose'))
    assert (mid, mid2) == (1, 2) and saved == [{'id': 1}, {'id': 2}] and s.last_match_id() == 2

    m = s.get_match(mid)
    assert 'raw_json' not in m and m['stage'] == 'ゴンズイ地区' and m['medal_image'] is None
    assert [p['slot'] for p in m['players']] == list(range(8)) and m['players'][1]['is_self'] == 1
    assert [e['t_ms'] for e in m['events']] == [1000, 40000, 70000, 90000]
    assert [(d['name'], d['rank'], d['position'], d['sig_id']) for d in m['medals']] == [('ナワバリ王', 'gold', 0, None), ('m_abcd', 'silver', 1, 'm_abcd')]
    assert s.get_match(99) is None

    lst = s.list_matches()
    assert [x['id'] for x in lst] == [2, 1] and lst[0]['weapon'] == 'わかばシューター' and lst[0]['medals'] == 2 and lst[0]['events'] == 4
    assert s.list_matches(limit=1, offset=1)[0]['id'] == 1
    assert s.summary() == {'matches': 2, 'wins': 1, 'last_id': 2, 'unlabelled_signatures': s.summary()['unlabelled_signatures']}

    st = s.stats()
    assert st['weapon_stats'] == [{'weapon': 'わかばシューター', 'games': 2, 'wins': 1, 'win_pct': 50.0, 'avg_ka': 1.0, 'avg_d': 7.0, 'avg_sp': 2.0, 'avg_points': 1001.0}]
    assert st['stage_stats'][0]['stage'] == 'ゴンズイ地区' and st['stage_stats'][0]['games'] == 2
    assert st['enemy_weapon_stats'][0] == {'weapon': 'わかばシューター', 'seen': 6, 'wins': 3, 'win_pct': 50.0, 'killed_me': 0, 'i_killed': 0}
    assert st['enemy_weapon_stats'][1] == {'weapon': 'スプラローラー', 'seen': 2, 'wins': 1, 'win_pct': 50.0, 'killed_me': 2, 'i_killed': 2}
    assert sorted(st['medal_stats'], key=lambda r: r['name']) == [{'name': 'm_abcd', 'rank': 'silver', 'n': 2}, {'name': 'ナワバリ王', 'rank': 'gold', 'n': 2}]
    assert st['my_timeline'] == [{'from_s': 0, 'type': 'killed_by', 'n': 2}, {'from_s': 30, 'type': 'kill', 'n': 2}]

    ov = s.overlay('2026-09-16T20:30:00', limit=8)
    assert ov['session']['matches'] == 1 and ov['session']['losses'] == 1 and ov['session']['streak'] == {'kind': 'lose', 'n': 1}
    assert ov['recent'][0]['medals'] == [{'name': 'ナワバリ王', 'rank': 'gold', 'position': 0}, {'name': 'm_abcd', 'rank': 'silver', 'position': 1}]
    assert ov['all_time'] == {'matches': 2, 'wins': 1} and ov['session']['killed_by'] == [{'weapon': 'スプラローラー', 'n': 1}]
    assert s.overlay(None)['session']['streak'] == {'kind': 'lose', 'n': 1} and s.overlay(None)['session']['wins'] == 1

    assert s.signature_examples('m_abcd') == [{'match_id': 2, 'position': 1, 'medal_image': None}, {'match_id': 1, 'position': 1, 'medal_image': None}]
    assert s.signature_examples('s_test1') == [{'match_id': 2, 'rule_image': None, 'result_image': None}, {'match_id': 1, 'rule_image': None, 'result_image': None}]
    assert s.signature_examples('x_none') == []

    deleted = []; s.events.subscribe('match_deleted', deleted.append)
    s.delete_match(mid)
    assert deleted == [{'id': 1}] and s.get_match(mid) is None and s.summary()['matches'] == 1
    con = sqlite3.connect(s.db_path)                                # children went with the match (ON DELETE CASCADE)
    assert con.execute('SELECT COUNT(*) FROM match_players WHERE match_id = 1').fetchone()[0] == 0
    assert con.execute('SELECT COUNT(*) FROM events WHERE match_id = 1').fetchone()[0] == 0
    assert con.execute('SELECT COUNT(*) FROM medals WHERE match_id = 1').fetchone()[0] == 0
    assert con.execute('SELECT COUNT(*) FROM timeline WHERE match_id = 1').fetchone()[0] == 0
    con.close(); s.close()


def test_failed_migration_rolls_back(tmp_path):
    """DDL runs inside one transaction: a migration that dies half-way leaves the file as it was (plus the stamp)"""
    db = str(tmp_path / 'broken.db')
    con = sqlite3.connect(db); con.executescript(LEGACY_SCHEMA)
    con.execute("INSERT INTO matches (id, started_at, result) VALUES (1, '2026-09-13T10:00:00', 'win')")
    con.execute('CREATE TABLE medals_new (x INTEGER)')             # collides with the rebuild of medals, after matches was rebuilt
    con.commit(); con.close()
    migrate.adopt_legacy(db, log=lambda *_: None)                  # backup + ALTER-era columns + stamp 0001 (not transactional, harmless)
    before = table_sql(db, 'matches')
    with pytest.raises(Exception):
        upgrade(db, log=lambda *_: None)
    con = sqlite3.connect(db)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
    assert 'matches_new' not in names and 'my_matches' in names and 'medals_new' in names
    assert table_sql(db, 'matches') == before and con.execute('SELECT COUNT(*) FROM matches').fetchone()[0] == 1
    assert current_revision(db) == '0001'                           # adopted (stamped) but not migrated
    con.execute('DROP TABLE medals_new'); con.commit(); con.close()
    assert upgrade(db, log=lambda *_: None) == ('0001', head_revision()) and schema_diff(db) == []


def test_check_constraints_are_enforced(tmp_path):
    s = Store(db_path=str(tmp_path / 'chk.db'))
    match, players, events, medals, timeline = sample_match()
    with pytest.raises(Exception):
        s.insert_match(dict(match, result='tie'), players, events, medals, timeline)
    with pytest.raises(Exception):
        s.insert_match(match, players, [dict(t_ms=0, type='assist', slot=1)], medals, timeline)
    assert s.summary()['matches'] == 0
    s.close()
