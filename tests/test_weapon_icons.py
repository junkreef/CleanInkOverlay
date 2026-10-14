"""Captured weapon icon library: unknown icon groups and naming them, and the matcher's 'variant' stage.
    uv run pytest
"""
import json, os, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for p in (ROOT, os.path.join(ROOT, 'work')):
    if p not in sys.path: sys.path.insert(0, p)
from app.store import Store
from weapon_icons import IconLibrary, group_name
from weapon_match import IconSet, match
from test_db import sample_match


def row_crop(extra=False, colour=(40, 200, 240)):
    """a result-row crop (70x90): panel (2, 2, 2), separator bands at the top / bottom, a 30x20 icon, optionally with
    a 'scope' (an extra 12x5 part) on top"""
    c = np.full((70, 90, 3), 2, np.uint8)
    c[:12] = (60, 60, 60); c[66:] = (60, 60, 60)
    c[32:52, 30:60] = colour; c[40:44, 34:56] = (250, 250, 250)
    if extra: c[26:31, 40:52] = (30, 30, 30)
    return c


def test_unknown_group_is_kept_reloaded_and_named(tmp_path):
    lib = IconLibrary(str(tmp_path / 'captured'), str(tmp_path / 'samples'))
    gid = lib.new_group(row_crop(), '2026-10-15_20-00-00_win2')
    assert lib.groups() == [gid] and lib.wants(group_name(gid), '2026-10-15_20-05-00_win3')
    lib.add_sample(group_name(gid), row_crop(), '2026-10-15_20-05-00_win3'); lib.save()
    assert not (tmp_path / 'captured').exists() or not os.listdir(tmp_path / 'captured')   # groups are never shipped
    lib = IconLibrary(str(tmp_path / 'captured'), str(tmp_path / 'samples'))                # template rebuilt from the samples
    assert lib.groups() == [gid] and lib.templates[group_name(gid)].shape == (56, 56, 4)
    v = lib.version
    assert lib.label_group(gid, 'テストシューター') == 2 and lib.version > v
    lib.save()
    assert lib.groups() == [] and not (tmp_path / 'samples' / '_unknown' / gid).exists()
    assert sorted(os.listdir(tmp_path / 'samples' / 'テストシューター')) == ['2026-10-15_20-00-00_win2.png', '2026-10-15_20-05-00_win3.png']
    assert os.listdir(tmp_path / 'captured') == ['テストシューター.png']
    t = IconLibrary(str(tmp_path / 'captured'), str(tmp_path / 'samples')).templates['テストシューター']
    assert t[..., 3].any() and not t[0, :, 3].any() and not t[-1, :, 3].any()             # the icon, no band rows


def test_naming_a_group_fills_the_matches_that_saw_it(tmp_path):
    s = Store(db_path=str(tmp_path / 'icons.db'))
    s._icons = IconLibrary(str(tmp_path / 'captured'), str(tmp_path / 'samples'))
    gid = s._icons.new_group(row_crop(), '2026-10-15_20-00-00_lose2'); s._icons.save()
    match, players, *rest = sample_match()
    rows = [dict(row=r, hteam='ally' if r.startswith('win') else 'enemy', weapon='わかばシューター', weapon_unknown=None)
            for r in ('win1', 'win2', 'win3', 'win4', 'lose1', 'lose2', 'lose3', 'lose4')]
    rows[5].update(weapon=None, weapon_unknown=gid)                                      # lose2 = enemy, 2nd row
    players = [dict(p, result_row=p['slot'] % 4, weapon=None if p['slot'] in (5, 6) else p['weapon']) for p in players]
    mid = s.insert_match(dict(match, raw_json=json.dumps({'rows': rows}, ensure_ascii=False)), players, *rest)
    changed = []; s.events.subscribe('weapon_icons_changed', changed.append)
    assert [u['id'] for u in s.unknown_weapon_icons()] == [gid]
    assert s.unknown_weapon_icons()[0]['seen'][0] == {'match_id': mid, 'result_image': None, 'rows': ['lose2']}
    s.label_weapon_icon(gid, 'テストシューター')
    weapons = {p['slot']: p['weapon'] for p in s.get_match(mid)['players']}
    assert weapons[5] == 'テストシューター' and weapons[6] is None                         # only the row that showed the icon
    with s.Session() as ses:
        from app.db import Match
        raw = json.loads(ses.get(Match, mid).raw_json)
    assert raw['rows'][5]['weapon'] == 'テストシューター' and changed == [{'id': gid, 'name': 'テストシューター'}]
    assert s.unknown_weapon_icons() == [] and 'テストシューター' in s.weapon_names()
    s.close()


def test_a_part_the_captured_template_lacks_makes_a_variant(tmp_path):
    lib = IconLibrary(str(tmp_path / 'captured'), str(tmp_path / 'samples'))
    for i, r in enumerate(('win1', 'win2', 'lose3')): lib.add_sample('テストチャージャー', row_crop(), f'2026-10-15_20-0{i}-00_{r}')
    icons = IconSet({'テストチャージャー': lib.templates['テストチャージャー']}, captured={'テストチャージャー'})
    assert match(row_crop(), icons)[0][1:3] == ('テストチャージャー', 'natural')
    assert match(row_crop(extra=True), icons)[0][1:3] == ('テストチャージャー', 'variant')            # a scope it has not got
    assert match(row_crop(colour=(40, 120, 240)), icons)[0][1:3] == ('テストチャージャー', 'variant')  # other colours
    assert match(row_crop(extra=True), IconSet(icons))[0][2] == 'natural'                         # wiki icons are not checked
