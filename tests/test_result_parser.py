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
    starts 56 px further left; read from there it gives the same signature as after a long rule name. After 'ガチアサリ'
    (wider glyphs) it starts 6 px further right again and after 'ガチエリア' half a pixel (0.94 at +0 and +1), found by
    looking the name up over STAGE_SHIFT"""
    import cv2
    from result_parser import stage_x, banner_identify
    from signatures import Library
    lib = Library()
    for name, x, rule, stage in (('results/yagura2.png', 1005, 'ガチヤグラ', 'チョウザメ造船'),     # 2026-10-28_23-06-42.mp4
                                 ('results/asari1.png', 1005, 'ガチアサリ', 'バイガイ亭'),          # 2026-10-29_22-02-57.mp4
                                 ('results/area1.png', 1005, 'ガチエリア', 'マヒマヒリゾート＆スパ'),  # 2026-11-04_22-59-07.mp4
                                 ('gachi_scoreboard_ko.png', 1061, None, 'スメーシーワールド'),     # ガチホコバトル
                                 ('0268_result_scoreboard.png', 1061, 'ナワバリバトル', 'コンブトラック')):
        f = cv2.imread(os.path.join(ROOT, 'work', 'frames', name))
        assert stage_x(f) == x, name
        assert banner_identify(f, 'stage', lib, add_unknown=False)[1] == stage, name
        assert banner_identify(f, 'rule', lib, add_unknown=False)[1] == rule, name


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


def test_glyph_scores_are_pearson_correlations():
    """Glyphs.read scores every template with one matrix product: the same character and score as np.corrcoef
    against each template, on random glyph-like masks of every glyph set (holes filter included)"""
    import cv2
    from result_parser import Glyphs, glyph_boxes, norm_glyph, holes, HOLES, HOLE_SETS
    g = Glyphs(); rng = np.random.default_rng(0)
    for which, tpl in g.sets.items():
        for _ in range(20):
            m = np.zeros((40, 30), np.uint8); m[4:36, 4:26] = (rng.random((32, 22)) > 0.4)
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            boxes = [max(glyph_boxes(m, 1, 40, 1), key=lambda b: b[2] * b[3])]
            text, sc = g.read(m, boxes, which)
            v = norm_glyph(m, boxes[0]).ravel(); cands = tpl
            if which in HOLE_SETS: cands = {ch: t for ch, t in tpl.items() if HOLES.get(ch, 0) == holes(m, boxes[0])} or tpl
            ref = {ch: float(np.corrcoef(v, t.ravel())[0, 1]) for ch, t in cands.items()}
            best = max(ref, key=ref.get)
            assert text == best and abs(sc[0] - round(ref[best], 2)) < 1e-9, (which, text, best)
