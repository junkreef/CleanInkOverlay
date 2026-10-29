"""ガチルール counts ('N カウント' / 'ノックアウト!' and the teams' 'Np') on the judge screen and the scoreboard.
    uv run pytest
"""
import os, sys
import cv2
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if os.path.join(ROOT, 'work') not in sys.path: sys.path.insert(0, os.path.join(ROOT, 'work'))
from counts import read_judge_counts, read_scoreboard_counts
from result_parser import Glyphs

FRAMES = os.path.join(ROOT, 'work', 'frames')
G = Glyphs()


def frame(name):
    return cv2.imread(os.path.join(FRAMES, name))


def test_judge_knockout():
    j = read_judge_counts(frame('gachi_judge_ko_304.8.png'), G)        # 2026-10-28_22-51-57.mp4 at 304.8 s: ノックアウト! 500p / 0カウント 0p
    assert j == {'my': dict(count=100, ko=True, points=500), 'enemy': dict(count=0, ko=False, points=0)}


def test_judge_counts():
    j = read_judge_counts(frame('gachi_judge_count_720.7.png'), G)     # same video at 720.7 s: 68カウント 340p / 40カウント 200p
    assert j == {'my': dict(count=68, ko=False, points=340), 'enemy': dict(count=40, ko=False, points=200)}


def test_scoreboard_knockout():
    s = read_scoreboard_counts(frame('gachi_scoreboard_ko.png'), G)    # ノックアウト! / 0カウント, WIN! 500 p, LOSE... 0 p
    assert s == dict(left=dict(count=100, ko=True), right=dict(count=0, ko=False), win_points=500, lose_points=0)


def test_scoreboard_counts():
    s = read_scoreboard_counts(frame(os.path.join('results', 'yagura2.png')), G)  # ガチヤグラ, 2026-10-28_23-06-42.mp4: 43カウント / 40カウント, 215 p / 200 p
    assert s == dict(left=dict(count=43, ko=False), right=dict(count=40, ko=False), win_points=215, lose_points=200)


def test_turf_screens_have_no_counts():
    none_j = {'my': dict(count=None, ko=None, points=None), 'enemy': dict(count=None, ko=None, points=None)}
    none_s = dict(left=dict(count=None, ko=None), right=dict(count=None, ko=None), win_points=None, lose_points=None)
    for name in ('judge_lose_266.5.png', '0244_result_judd.png', '0246_result_pct.png', '0268_result_scoreboard.png'):
        f = frame(name)                                                # '45.7%' must not read as 45 カウント; the 'Np' there is not read
        assert read_judge_counts(f, G) == none_j, name
        assert read_scoreboard_counts(f, G) == none_s, name
