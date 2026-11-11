"""What a release (the zip for users without Python / git) relies on: the data folder apart from the program folder,
the user's additions kept apart from the shipped libraries, and the launcher's start-up steps.
    uv run pytest
"""
import json, os, sqlite3, subprocess, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for p in (ROOT, os.path.join(ROOT, 'work')):
    if p not in sys.path: sys.path.insert(0, p)
from app import launch
from app.db import upgrade, current_revision, head_revision
from app.store import Store
from signatures import Library
from weapon_icons import IconLibrary
from test_db import sample_match
from test_weapon_icons import row_crop


def write_lib(path, items):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh: json.dump(items, fh, ensure_ascii=False)


def test_the_users_signature_file_only_holds_what_the_user_added(tmp_path):
    shipped, own = str(tmp_path / 'program' / 'signatures.json'), str(tmp_path / 'data' / 'signatures.json')
    write_lib(shipped, {'s_a': dict(kind='stage', label='ユノハナ大渓谷', sig=[1.0, 0.0]), 's_b': dict(kind='stage', label=None, sig=[0.0, 1.0])})
    lib = Library(own, shipped=shipped)
    assert lib.items['s_a']['label'] == 'ユノハナ大渓谷' and lib.adopted == []
    lib.items['m_new'] = dict(kind='medal', label=None, sig=[0.5, 0.5])          # seen here for the first time
    lib.label('s_b', 'ゴンズイ地区'); lib.save()
    assert json.load(open(own, encoding='utf-8')) == {'s_b': dict(kind='stage', label='ゴンズイ地区', sig=[0.0, 1.0]),
                                                      'm_new': dict(kind='medal', label=None, sig=[0.5, 0.5])}
    assert json.load(open(shipped, encoding='utf-8'))['s_b']['label'] is None    # the program folder is never written
    # a newer release names the medal and corrects s_a; the user's own label for s_b stays
    write_lib(shipped, {'s_a': dict(kind='stage', label='ユノハナ大渓谷 (訂正)', sig=[1.0, 0.0]), 's_b': dict(kind='stage', label='別の名前', sig=[0.0, 1.0]),
                        'm_new': dict(kind='medal', label='塗りポイント No.1', sig=[0.5, 0.5])})
    lib = Library(own, shipped=shipped)
    assert {k: it['label'] for k, it in lib.items.items()} == {'s_a': 'ユノハナ大渓谷 (訂正)', 's_b': 'ゴンズイ地区', 'm_new': '塗りポイント No.1'}
    assert lib.adopted == ['m_new']
    lib.save()
    assert list(json.load(open(own, encoding='utf-8'))) == ['s_b']
    assert Library(own, shipped=shipped).adopted == []


def test_a_release_store_writes_under_the_data_folder_and_adopts_shipped_labels(tmp_path):
    program, data = tmp_path / 'program' / 'assets', tmp_path / 'data'
    write_lib(str(program / 'signatures.json'), {'s_a': dict(kind='stage', label='ユノハナ大渓谷', sig=[1.0, 0.0])})
    s = Store(root=str(data), db_path=str(data / 'data' / 'splatoon.db'), shipped_assets=str(program))
    match, players, events, medals, timeline = sample_match()                    # stage s_test1 and medal m_abcd are unknown
    mid = s.insert_match(dict(match, stage=None), players, events, medals, timeline)
    s.signatures().items.update({'s_test1': dict(kind='stage', label=None, sig=[0.0, 1.0]), 'm_abcd': dict(kind='medal', label=None, sig=[0.3, 0.7])})
    s.label_signature('s_test1', 'ゴンズイ地区')
    assert s.get_match(mid)['stage'] == 'ゴンズイ地区'
    assert sorted(json.load(open(data / 'assets' / 'signatures.json', encoding='utf-8'))) == ['m_abcd', 's_test1']
    assert list(json.load(open(program / 'signatures.json', encoding='utf-8'))) == ['s_a']
    img = s.save_image('2026-11-11_20-00-00', 'result', np.zeros((4, 4, 3), np.uint8))
    assert img == 'samples/matches/2026-11-11_20-00-00_result.png' and s.file_path(img) == str(data / 'samples' / 'matches' / '2026-11-11_20-00-00_result.png')
    s.close()
    # the next release ships the medal's name: the stored medal becomes readable at the next start
    write_lib(str(program / 'signatures.json'), {'s_a': dict(kind='stage', label='ユノハナ大渓谷', sig=[1.0, 0.0]),
                                                 'm_abcd': dict(kind='medal', label='バトル No.1', sig=[0.3, 0.7])})
    s = Store(root=str(data), db_path=str(data / 'data' / 'splatoon.db'), shipped_assets=str(program))
    assert s.unlabelled_signatures() == []
    assert [m['name'] for m in s.get_match(mid)['medals']] == ['ナワバリ王', 'バトル No.1']
    assert list(json.load(open(data / 'assets' / 'signatures.json', encoding='utf-8'))) == ['s_test1']
    s.close()


def test_rebuilt_icon_templates_go_to_the_users_folder_and_win_over_the_shipped_ones(tmp_path):
    shipped, own, samples = tmp_path / 'program', tmp_path / 'data' / 'captured', tmp_path / 'data' / 'samples'
    first = IconLibrary(str(shipped), str(tmp_path / 'author_samples'))          # the author's side: makes the shipped template
    for i in range(8): first.add_sample('テストシューター', row_crop(), f'2026-10-15_20-0{i}-00_win{i % 4 + 1}')
    first.save()
    before = (shipped / 'テストシューター.png').read_bytes()
    lib = IconLibrary(str(own), str(samples), shipped_dir=str(shipped))
    assert list(lib.templates) == ['テストシューター'] and lib.shipped == {'テストシューター'}
    stems = [f'2026-11-11_21-0{i}-00_lose{i % 4 + 1}' for i in range(8)]
    for st in stems[:7]: lib.add_sample('テストシューター', row_crop(colour=(40, 200, 200)), st)
    lib.save()
    assert not own.exists()                                                      # shipped template kept until the local samples are complete
    lib.add_sample('テストシューター', row_crop(colour=(40, 200, 200)), stems[7]); lib.save()
    assert os.listdir(own) == ['テストシューター.png'] and (shipped / 'テストシューター.png').read_bytes() == before
    lib = IconLibrary(str(own), str(samples), shipped_dir=str(shipped))
    assert not np.array_equal(lib.templates['テストシューター'], lib.shipped_templates['テストシューター'])
    for st in stems: lib.drop_sample('テストシューター', st)                       # all of them were wrong: back to the shipped one
    lib.save()
    assert os.listdir(own) == [] and lib.templates['テストシューター'] is lib.shipped_templates['テストシューター']


def test_the_data_folder_follows_cleanink_home():
    """app.paths reads CLEANINK_HOME when it is imported (the launcher sets it first): config.toml and the DB move with it"""
    code = "from app import config, paths; from app.db import DEFAULT_DB; print(paths.SPLIT); print(config.PATH); print(DEFAULT_DB)"
    home = os.path.join(os.path.dirname(ROOT), 'somewhere else')
    run = lambda env: subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout.split('\n')[:3]
    env = {k: v for k, v in os.environ.items() if k != 'CLEANINK_HOME'}
    assert run(env) == ['False', os.path.join(ROOT, 'config.toml'), os.path.join(ROOT, 'data', 'splatoon.db')]
    assert run(dict(env, CLEANINK_HOME=home)) == ['True', os.path.join(home, 'config.toml'), os.path.join(home, 'data', 'splatoon.db')]


def test_the_launcher_keeps_the_data_under_localappdata(tmp_path):
    assert launch.data_home({'LOCALAPPDATA': str(tmp_path)}) == str(tmp_path / 'CleanInkOverlay')
    assert launch.data_home({'LOCALAPPDATA': str(tmp_path), 'CLEANINK_HOME': str(tmp_path / 'x')}) == str(tmp_path / 'x')


def test_the_launcher_migrates_an_old_db_after_a_backup_and_refuses_a_newer_one(tmp_path):
    from alembic import command
    from app.db.migrate import alembic_config
    new = str(tmp_path / 'first' / 'splatoon.db'); lines = []
    assert launch.migrate(new, log=lines.append) and current_revision(new) == head_revision()    # a first start creates it
    db = str(tmp_path / 'data' / 'splatoon.db'); os.makedirs(tmp_path / 'data')
    command.upgrade(alembic_config(db), '0003')                                                   # a file left by an older version
    assert launch.migrate(db, log=lines.append) and current_revision(db) == head_revision()
    assert [p for p in os.listdir(tmp_path / 'data') if '.bak-' in p and p.endswith('-0003')]
    Store(root=str(tmp_path), db_path=db).close()                                                 # the store takes it now
    con = sqlite3.connect(db); con.execute("UPDATE alembic_version SET version_num = '9999'"); con.commit(); con.close()
    lines.clear()
    assert not launch.migrate(db, log=lines.append) and current_revision(db) == '9999'
    assert not [p for p in os.listdir(tmp_path / 'data') if p.endswith('-9999')]                  # refused before any backup
    assert '新しい' in lines[0] and '最新版' in lines[1]


def test_the_log_folder_keeps_the_newest_files(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'stdout', sys.stdout); monkeypatch.setattr(sys, 'stderr', sys.stderr)   # restored after the test
    (tmp_path / 'logs').mkdir()
    for i in range(30): (tmp_path / 'logs' / f'2026-10-{i + 1:02d}_20-00-00.log').write_text('x')
    p = launch.start_log(str(tmp_path), now=0)
    print('ひとこと')
    sys.stdout.fh.close(); sys.stderr.fh.close()
    logs = sorted(os.listdir(tmp_path / 'logs'))
    assert len(logs) == launch.LOGS_KEPT and logs[0] == os.path.basename(p) and logs[1] == '2026-10-12_20-00-00.log'
    assert 'ひとこと' in open(p, encoding='utf-8').read()
