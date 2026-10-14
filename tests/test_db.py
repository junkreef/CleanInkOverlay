"""DB layer: fresh files, model <-> migration parity, the Store's read/write API, the on-request migration policy.
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


def test_fresh_db_is_created_at_head_and_matches_models(tmp_path):
    db = str(tmp_path / 'new.db')
    assert upgrade(db) == (None, head_revision())
    assert current_revision(db) == head_revision()
    assert schema_diff(db) == []                                    # `alembic revision --autogenerate` would be empty
    assert upgrade(db) == (head_revision(), head_revision())        # no-op, no backup
    assert not [p for p in os.listdir(tmp_path) if '.bak-' in p]


def test_store_refuses_outdated_db_and_upgrade_backs_up_first(tmp_path):
    """migrations of existing files are an explicit step (python -m app.db upgrade), never a side effect of opening"""
    db = str(tmp_path / 'old.db'); upgrade(db)
    con = sqlite3.connect(db); con.execute("UPDATE alembic_version SET version_num = '0000'"); con.commit(); con.close()
    with pytest.raises(migrate.SchemaOutdated, match='python -m app.db upgrade'):
        Store(db_path=db)
    assert current_revision(db) == '0000' and not [p for p in os.listdir(tmp_path) if '.bak-' in p]   # untouched
    con = sqlite3.connect(db); con.execute("UPDATE alembic_version SET version_num = ?", (head_revision(),)); con.commit(); con.close()
    Store(db_path=db).close()


def test_backup_copies_the_file_next_to_itself(tmp_path):
    """upgrade() calls this before touching an existing file; the name carries the date and the old revision"""
    db = str(tmp_path / 'b.db'); s = Store(db_path=db); s.insert_match(*sample_match()); s.close()
    first = migrate.backup(db, '0001'); second = migrate.backup(db, '0001')
    assert os.path.basename(first).startswith('b.db.bak-') and first.endswith('-0001') and second == first + '-2'
    con = sqlite3.connect(first)
    assert con.execute('SELECT COUNT(*) FROM matches').fetchone()[0] == 1 and con.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    con.close()


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
    assert s.summary() == {'matches': 2, 'wins': 1, 'last_id': 2, 'unlabelled_signatures': s.summary()['unlabelled_signatures'],
                           'unknown_weapon_icons': s.summary()['unknown_weapon_icons']}

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
    for t in ('match_players', 'events', 'medals', 'timeline'):
        assert con.execute(f'SELECT COUNT(*) FROM {t} WHERE match_id = 1').fetchone()[0] == 0
    con.close(); s.close()


def test_check_constraints_are_enforced(tmp_path):
    s = Store(db_path=str(tmp_path / 'chk.db'))
    match, players, events, medals, timeline = sample_match()
    with pytest.raises(Exception):
        s.insert_match(dict(match, result='tie'), players, events, medals, timeline)
    with pytest.raises(Exception):
        s.insert_match(match, players, [dict(t_ms=0, type='assist', slot=1)], medals, timeline)
    assert s.summary()['matches'] == 0
    s.close()
