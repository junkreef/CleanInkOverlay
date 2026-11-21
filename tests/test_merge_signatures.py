"""Merging other people's signatures.json into ours (work/merge_signatures.py).
    uv run pytest
"""
import json, os, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for p in (ROOT, os.path.join(ROOT, 'work')):
    if p not in sys.path: sys.path.insert(0, p)
from merge_signatures import merge, main

RNG = np.random.default_rng(7)
A, B, C = (RNG.random(64).round(3) for _ in range(3))          # three different texts (correlation near 0)


def item(sig, label, kind='medal'):
    return {'kind': kind, 'label': label, 'sig': [float(v) for v in sig]}


def near(sig):
    """the same text seen by someone else: a few pixels off, so another id"""
    s = sig.copy(); s[:4] = 1 - s[:4]; return s


def outcomes(report):
    return {(r[0], r[1]) for r in report}


def test_new_text_is_added_and_unlabelled_entries_are_ignored():
    ours = {'m_a': item(A, 'ナイスダマ')}
    rep = merge(ours, {'m_b': item(B, 'ガチホコブロック No.1'), 'm_c': item(C, None)})
    assert outcomes(rep) == {('added', 'm_b')}
    assert ours['m_b']['label'] == 'ガチホコブロック No.1' and 'm_c' not in ours


def test_same_id_same_label_is_known_and_an_unlabelled_id_of_ours_is_named():
    ours = {'m_a': item(A, 'ナイスダマ'), 'm_b': item(B, None)}
    rep = merge(ours, {'m_a': item(A, 'ナイスダマ'), 'm_b': item(B, 'ベストカウント更新')})
    assert outcomes(rep) == {('known', 'm_a'), ('named', 'm_b')}
    assert ours['m_b']['label'] == 'ベストカウント更新'


def test_another_signature_of_a_text_we_know_is_not_added():
    ours = {'m_a': item(A, 'ナイスダマ')}
    rep = merge(ours, {'m_x': item(near(A), 'ナイスダマ')})
    assert [r[0] for r in rep] == ['known'] and set(ours) == {'m_a'}


def test_conflicts_are_reported_and_not_merged():
    ours = {'m_a': item(A, 'ナイスダマ')}
    rep = merge(ours, {'m_a': item(A, 'ちがう名前'), 'm_x': item(near(A), 'べつの名前')})
    assert outcomes(rep) == {('conflict', 'm_a'), ('conflict', 'm_x')}
    assert ours == {'m_a': item(A, 'ナイスダマ')}


def test_a_new_signature_of_an_unnamed_text_names_ours_too():
    ours = {'m_a': item(A, None)}
    rep = merge(ours, {'m_x': item(near(A), 'ガチホコ運んだ時間 No.1')})
    assert outcomes(rep) == {('named', 'm_a'), ('added', 'm_x')}
    assert ours['m_a']['label'] == ours['m_x']['label'] == 'ガチホコ運んだ時間 No.1'


def test_a_close_but_different_medal_is_added_not_a_conflict():
    """'reads as' uses the recorder's threshold for the kind: medals 0.8 (ガチホコブロック No.1 is 0.72 to ガチエリア関与 No.1)"""
    other = 0.55 * (A - A.mean()) + 0.45 * (B - B.mean())
    assert 0.6 < np.corrcoef(A, other)[0, 1] < 0.8
    ours = {'m_a': item(A, 'ガチエリア関与 No.1')}
    rep = merge(ours, {'m_x': item(other, 'ガチホコブロック No.1')})
    assert [r[0] for r in rep] == ['added']


def test_other_kinds_and_sizes_do_not_match():
    ours = {'s_a': item(A, 'コンブトラック', kind='stage')}
    rep = merge(ours, {'m_x': item(near(A), 'ナイスダマ'), 's_y': item(np.concatenate([B, B]), '海女美術大学', kind='stage')})
    assert outcomes(rep) == {('added', 'm_x'), ('skipped', 's_y')}


def test_cli_dry_run_writes_nothing_and_apply_writes(tmp_path, capsys):
    lib, theirs = tmp_path / 'signatures.json', tmp_path / 'theirs.json'
    lib.write_text(json.dumps({'m_a': item(A, 'ナイスダマ')}, ensure_ascii=False), encoding='utf-8')
    theirs.write_text(json.dumps({'m_b': item(B, 'ベストカウント更新'), 'n_z': item(C, 'ひらパー', kind='name')}, ensure_ascii=False), encoding='utf-8')
    main([str(theirs), '--library', str(lib)])
    assert set(json.loads(lib.read_text(encoding='utf-8'))) == {'m_a'}
    assert 'dry run' in capsys.readouterr().out
    main([str(theirs), '--library', str(lib), '--apply'])
    assert set(json.loads(lib.read_text(encoding='utf-8'))) == {'m_a', 'm_b'}      # kind 'name' is dropped
