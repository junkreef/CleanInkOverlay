"""Judge screen (paint % bar + WIN! / LOSE...) reading: the fallback when the result screen is skipped.
    uv run pytest
"""
import os, sys
import cv2
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if os.path.join(ROOT, 'work') not in sys.path: sys.path.insert(0, os.path.join(ROOT, 'work'))
from judge import read_judge, read_label, read_pct, PCT_L, PCT_R
from result_parser import Glyphs

FRAMES = os.path.join(ROOT, 'work', 'frames')
G = Glyphs()


def frame(name):
    return cv2.imread(os.path.join(FRAMES, name))


def test_lose_screen_reads_result_and_pct():
    j = read_judge(frame('judge_lose_266.5.png'), G)               # 2026-10-11_22-14-08.mp4 at 266.5 s (scoreboard: 45.7 / 50.7, lose)
    assert (j['result'], j['my_pct'], j['enemy_pct']) == ('lose', 45.7, 50.7)


def test_a_covered_digit_is_not_read():
    f = frame('0246_result_pct.png')                               # a squid hides the 3 of 38.3%: the rest alone looks like '8.3%'
    assert read_label(f)[0] == 'win'
    assert read_pct(f, PCT_L, G)[0] == '54.4%'
    assert read_pct(f, PCT_R, G) == ('', 0.0)
    assert read_judge(f, G) is None


def test_other_screens_are_no_judge_screen():
    assert read_judge(frame('0244_result_judd.png'), G) is None    # still counting: no label yet
    assert read_judge(frame('0250_result_team.png'), G) is None    # team poses: label without the bar
    for name in ('0060_ingame_early.png', '0268_result_scoreboard.png', '0041_match_start_rule.png', '0236_finish.png'):
        assert read_label(frame(name))[0] is None, name
