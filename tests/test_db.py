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


def test_a_new_store_offers_every_main_weapon_from_the_master(tmp_path):
    """a fresh install has no templates for some weapons; their names still come from assets/weapons.json"""
    s = Store(root=str(tmp_path), db_path=str(tmp_path / 'new.db'))
    names = s.weapon_names()
    assert len(names) == 174 and 'L3リールガン' in names and 'ガチホコ' not in names and 'ブキ無し' not in names
    s.close()


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
    assert st['enemy_weapon_stats'][0] == {'weapon': 'わかばシューター', 'seen': 6, 'seen_matches': 2, 'wins': 1, 'win_pct': 50.0, 'killed_me': 0, 'i_killed': 0}
    assert st['enemy_weapon_stats'][1] == {'weapon': 'スプラローラー', 'seen': 2, 'seen_matches': 2, 'wins': 1, 'win_pct': 50.0, 'killed_me': 2, 'i_killed': 2}
    assert sorted(st['medal_stats'], key=lambda r: r['name']) == [{'name': 'm_abcd', 'rank': 'silver', 'n': 2}, {'name': 'ナワバリ王', 'rank': 'gold', 'n': 2}]
    assert st['my_timeline'] == [{'from_s': 0, 'type': 'killed_by', 'n': 2}, {'from_s': 30, 'type': 'kill', 'n': 2}]
    assert st['overview'][0]['games'] == 2 and st['overview'][0]['wins'] == 1 and st['overview'][0]['losses'] == 1
    assert [r['result'] for r in st['recent']] == ['lose', 'win'] and [r['games'] for r in st['daily_stats']] == [2]

    later = s.stats(since='2026-09-16T20:30:00')                 # only the second match (the loss)
    assert later['overview'][0]['games'] == 1 and later['overview'][0]['losses'] == 1 and later['weapon_stats'][0]['wins'] == 0
    assert later['enemy_weapon_stats'][1] == {'weapon': 'スプラローラー', 'seen': 1, 'seen_matches': 1, 'wins': 0, 'win_pct': 0.0, 'killed_me': 1, 'i_killed': 1}
    assert later['medal_stats'][0]['n'] == 1 and [r['n'] for r in later['my_timeline']] == [1, 1]
    assert s.stats(mode='no such mode')['overview'][0]['games'] == 0 and s.stats(mode='no such mode')['weapon_stats'] == []

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


def test_gachi_counts_knockouts_and_the_rule_filter(tmp_path):
    s = Store(db_path=str(tmp_path / 'gachi.db'))
    s.insert_match(*sample_match())                                                     # ナワバリ, win
    for started, rule, result, mc, ec, ko in (('2026-09-16T21:00:00', 'ガチヤグラ', 'win', 100, 0, 1), ('2026-09-16T21:10:00', 'ガチヤグラ', 'lose', 62, 90, 0),
                                               ('2026-09-16T21:20:00', None, 'lose', 0, 100, 1)):   # the last: rule screen not labelled yet
        match, players, *rest = sample_match(started, result)
        match.update(mode='バンカラマッチ(チャレンジ)', rule=rule, my_pct=None, enemy_pct=None, my_count=mc, enemy_count=ec, knockout=ko)
        s.insert_match(match, players, *rest)

    assert [(m['my_count'], m['enemy_count'], m['knockout']) for m in s.list_matches()] == [(0, 100, 1), (62, 90, 0), (100, 0, 1), (None, None, None)]
    assert s.overlay(None)['last']['knockout'] == 1

    o = s.stats()['overview'][0]
    assert (o['games'], o['count_games'], o['ko_wins'], o['ko_losses'], o['avg_my_count'], o['avg_enemy_count']) == (4, 3, 1, 1, 54.0, 63.3)
    g = s.stats(rule='@gachi')
    assert g['overview'][0]['games'] == 3 and [r['result'] for r in g['recent']] == ['lose', 'lose', 'win']
    assert s.stats(rule='ガチヤグラ')['overview'][0]['games'] == 2 and s.stats(rule='ナワバリバトル')['overview'][0]['ko_wins'] is None
    assert s.stats()['rules'] == ['ガチヤグラ', 'ナワバリバトル']
    assert {r['rule']: (r['games'], r['wins'], r['ko_wins'], r['ko_losses']) for r in s.stats()['rule_stats']} == {
        'ガチヤグラ': (2, 1, 1, 0), None: (1, 0, 0, 1), 'ナワバリバトル': (1, 1, None, None)}
    s.close()


def test_objective_timeline_and_the_rule_name_of_the_rule_screen(tmp_path):
    s = Store(root=str(tmp_path), db_path=str(tmp_path / 'obj.db'))            # its own signatures.json under tmp_path
    match, players, events, medals, _ = sample_match()
    match.update(rule=None, raw_json=json.dumps({'title_id': 't_test1'}))
    timeline = [dict(t_s=0, points=None, gauge=0.0, ready=0, obj_pos=0.3, obj_holder=None, my_best=0.0, enemy_best=0.0, my_count=3, enemy_count=0, overtime=0),
                dict(t_s=301, points=None, gauge=0.5, ready=0, obj_pos=78.1, obj_holder='my', my_best=78.1, enemy_best=80.0, overtime=1)]
    mid = s.insert_match(match, players, events, medals, timeline)
    assert [(r['t_s'], r['obj_pos'], r['obj_holder'], r['my_best'], r['my_count'], r['overtime']) for r in s.get_match(mid)['timeline']] == [(0, 0.3, None, 0.0, 3, 0), (301, 78.1, 'my', 78.1, None, 1)]
    s.signatures().items['t_test1'] = {'kind': 'title', 'label': None, 'sig': [0.0]}
    assert s.signature_examples('t_test1') == [{'match_id': mid, 'rule_image': None, 'result_image': None}]
    s.label_signature('t_test1', 'ガチヤグラ')                                        # naming the rule screen's rule name fills rule
    assert s.get_match(mid)['rule'] == 'ガチヤグラ'
    s.close()


def test_check_constraints_are_enforced(tmp_path):
    s = Store(db_path=str(tmp_path / 'chk.db'))
    match, players, events, medals, timeline = sample_match()
    with pytest.raises(Exception):
        s.insert_match(dict(match, result='tie'), players, events, medals, timeline)
    with pytest.raises(Exception):
        s.insert_match(match, players, [dict(t_ms=0, type='assist', slot=1)], medals, timeline)
    assert s.summary()['matches'] == 0
    s.close()


def test_prune_images_drops_old_screens_and_clears_the_rows(tmp_path):
    """old screens go (and the match row forgets them); recent ones and the screens of unlabelled signatures stay.
    Nothing but the files decides: a release has neither git nor a repository around its data folder"""
    import time
    s = Store(root=str(tmp_path), db_path=str(tmp_path / 'p.db'))
    old = time.time() - 30 * 86400
    def screen(name, age=old):
        p = tmp_path / 'samples' / 'matches' / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'png')
        os.utime(p, (age, age)); return f'samples/matches/{name}'
    match, players, events, medals, timeline = sample_match()
    mid = s.insert_match(dict(match, raw_json='{}', rule_image=screen('a_rule.png'), result_image=screen('a_result.png'), medal_image=screen('a_medals.png')),
                         players, events, medals=[dict(name='ナワバリ王', rank='gold', position=0)], timeline=timeline)
    s.insert_match(dict(match, medal_image=screen('b_medals.png')), players, events, medals, timeline)    # shows unlabelled m_abcd / s_test1
    s.signatures().items.update({'m_abcd': {'kind': 'medal'}, 's_test1': {'kind': 'stage'}})
    screen('c_rule.png', age=time.time())
    (tmp_path / 'samples' / 'matches' / 'a.json').write_text('{}'); os.utime(tmp_path / 'samples' / 'matches' / 'a.json', (old, old))
    assert sorted(s.prune_images(keep_days=7, dry=True)) == ['samples/matches/a_medals.png', 'samples/matches/a_result.png', 'samples/matches/a_rule.png']
    assert (tmp_path / 'samples' / 'matches' / 'a_rule.png').exists()                                      # dry: nothing removed
    s.prune_images(keep_days=7)
    assert sorted(os.listdir(tmp_path / 'samples' / 'matches')) == ['a.json', 'b_medals.png', 'c_rule.png']
    m = s.get_match(mid); assert (m['rule_image'], m['result_image'], m['medal_image']) == (None, None, None)
    s.close()


def test_labelling_a_banner_signature_fills_the_matches_stored_under_it(tmp_path):
    """mode / rule / stage are read from the result banner by signature; a label given later fills the NULL column of
    the matches that carry the id in raw_json, and leaves other matches alone"""
    from signatures import Library
    s = Store(db_path=str(tmp_path / 'lab.db'))
    s._sig = Library(str(tmp_path / 'sig.json'))
    s._sig.items['m_event'] = dict(kind='mode', label=None, sig=[0.0] * 4)
    match = sample_match()[0]
    ids = [s.insert_match(dict(match, mode=None, raw_json=json.dumps({'mode_id': mid})), *sample_match()[1:]) for mid in ('m_event', 'm_other')]
    s.label_signature('m_event', 'イベントマッチ')
    assert [s.get_match(i)['mode'] for i in ids] == ['イベントマッチ', None]
    assert Library(str(tmp_path / 'sig.json')).items['m_event']['label'] == 'イベントマッチ'
    s.close()
