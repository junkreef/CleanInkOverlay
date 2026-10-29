"""Result screen banner reading (mode / rule / stage signatures).
    uv run pytest
"""
import os, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if os.path.join(ROOT, 'work') not in sys.path: sys.path.insert(0, os.path.join(ROOT, 'work'))
from result_parser import banner_signature, BANNER


def frame_with(*boxes):
    """a black 1080p frame with white boxes (x, y, w, h) on it"""
    f = np.zeros((1080, 1920, 3), np.uint8)
    for x, y, w, h in boxes: f[y:y + h, x:x + w] = 255
    return f


def test_a_speck_in_the_banner_is_no_text():
    b = BANNER['stage']; x, y = b['x'], b['y']
    assert banner_signature(frame_with(), 'stage') is None
    assert banner_signature(np.full((1080, 1920, 3), 128, np.uint8), 'mode') is None         # no dark tag: an empty band, no crash
    assert banner_signature(frame_with((x + 60, y + 8, 5, 5)), 'stage') is None              # 25 px of white, 5 px wide
    words = [(x + i * 22, y + 2, 16, 18) for i in range(5)]                                   # five "glyphs", ~100 px wide
    sig = banner_signature(frame_with(*words), 'stage')
    assert sig is not None and sig.max() > 0.9


def test_the_stage_name_moves_left_after_a_short_rule_name():
    """'ガチヤグラ' is 2 characters shorter than 'ナワバリバトル' / 'ガチホコバトル', so the stage name after it in the same tag
    starts 56 px further left; read from there it gives the same signature as after a long rule name"""
    import cv2
    from result_parser import stage_x, BANNER_THR
    from signatures import Library
    lib = Library()
    for name, x, stage in (('results/yagura2.png', 1005, 'チョウザメ造船'),          # 2026-10-28_23-06-42.mp4, ガチヤグラ
                           ('gachi_scoreboard_ko.png', 1061, 'スメーシーワールド'),  # ガチホコバトル
                           ('0268_result_scoreboard.png', 1061, 'コンブトラック')):  # ナワバリバトル
        f = cv2.imread(os.path.join(ROOT, 'work', 'frames', name))
        assert stage_x(f) == x, name
        assert lib.identify(banner_signature(f, 'stage'), 'stage', add_unknown=False, thr=BANNER_THR)[1] == stage, name


def test_rows_of_the_labelled_scoreboards():
    """points / kills / deaths / specials of every hand-read scoreboard (GT); hoko1 and yagura3 have the small 8s
    (x08 read as x06 / x00 before the hole count) and yagura2 a 6 that read as 8"""
    import cv2
    from result_parser import GT, Glyphs, row_glyphs
    from weapon_match import RESULT_ROWS
    g = Glyphs()
    for k, gt in GT.items():
        f = cv2.imread(os.path.join(ROOT, 'work', 'frames', 'results', k + '.png'))
        for row, pts, kills, deaths, specials in gt['rows']:
            pm, pb, sm, sb = row_glyphs(f, RESULT_ROWS[row])
            assert (g.read(pm, pb, 'big')[0], g.read(sm, sb, 'small')[0]) == (pts, kills + deaths + specials), (k, row)


def test_a_panel_8_is_no_6():
    """2026-10-29 00:59 (live): the own panel's 'x08' kills; the panel's '6' was learnt from stored rows that held 08 as 06"""
    import cv2, panel
    from result_parser import Glyphs
    f = cv2.imread(os.path.join(ROOT, 'work', 'frames', 'panel_kills_08.png'))
    g = Glyphs()
    assert [g.read(m, b, which)[0] for (m, b), which in zip(panel.parts(f), ('panel_big',) + ('panel_small',) * 3)] == ['1532p', '08', '03', '04']
