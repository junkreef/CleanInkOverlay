"""Own result panel (the 表彰 screen) reading: the own row + stage of a match whose scoreboard is skipped.
    uv run pytest
"""
import json, os, sys
import cv2
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if os.path.join(ROOT, 'work') not in sys.path: sys.path.insert(0, os.path.join(ROOT, 'work'))
from panel import read_panel, learn_weapon
from result_parser import Glyphs
from signatures import Library, LIB

FRAMES = os.path.join(ROOT, 'work', 'frames', 'medals')
G = Glyphs()


def frame(name):
    return cv2.imread(os.path.join(FRAMES, name))


def library_without_panel_weapons(tmp_path):
    """the real stage / mode / rule labels, no panel weapon icons learnt yet; in a temp file"""
    items = {k: v for k, v in json.load(open(LIB, encoding='utf-8')).items() if v['kind'] != 'panel_weapon'}
    p = tmp_path / 'signatures.json'; p.write_text(json.dumps(items, ensure_ascii=False), encoding='utf-8')
    return Library(str(p))


def test_own_row_and_banner(tmp_path):
    p = read_panel(frame('14-13_m1.png'), G, library_without_panel_weapons(tmp_path))   # 2026-09-12_14-13-43.mp4 match 1; scoreboard row win1
    assert (p['points'], p['kills_assists'], p['deaths'], p['specials']) == (1230, 6, 4, 4)
    assert (p['stage'], p['mode'], p['rule']) == ('コンブトラック', 'レギュラーマッチ', 'ナワバリバトル')
    p = read_panel(frame('14-35_m2.png'), G, library_without_panel_weapons(tmp_path))
    assert (p['points'], p['kills_assists'], p['deaths'], p['specials'], p['stage']) == (1165, 3, 3, 3, 'ユノハナ大渓谷')


def test_weapon_icon_is_learnt_from_a_scoreboard(tmp_path):
    lib = library_without_panel_weapons(tmp_path)
    p = read_panel(frame('14-13_m1.png'), G, lib)
    assert p['weapon'] is None and not any(v['kind'] == 'panel_weapon' for v in lib.items.values())   # reading adds nothing
    assert learn_weapon(lib, p['weapon_sig'], 'プロモデラーMG')
    assert not learn_weapon(lib, p['weapon_sig'], 'プロモデラーMG')                                   # already known
    assert read_panel(frame('14-35_m2.png'), G, lib)['weapon'] == 'プロモデラーMG'                     # another match, same weapon
