"""The replay viewer (メモリープレイヤー): its mark top left tells a replay from a live match (1080p).

A past battle watched with the game's replay feature shows the very screens of a match - the rule screen with the 8
cards, the HUD, Finish!, the judge screen, the WIN! / LOSE... team pose - so the recorder took it for a match and stored
it a second time (2026-04-08_00-24-01.mp4: rule screen 5.5 s, HUD 18.7 s, judge 207.8 s, stored at the end as a ナワバリ
win 72.5-24.3). Throughout the playback the viewer keeps a mark top left: a magenta rounded box (x 46-140, y 38-105,
BGR ~(140, 0, 215)) with a white "replay" icon in it (a circular arrow around a play triangle, x 66-118, y 46-97). It
does not move or blink; it is there over the rule screen, the HUD and Finish!, washed out (pink on white) by the
game's white / dark fades, and gone only for ~0.6 s in two fades. It is not on the judge screen and the team pose
that close the playback (the WIN! / LOSE... label sits there). The same mark, same place, is on the ガチエリア
test frames added 2026-10-29 (work/frames/gachi_rule_area.png, gachi_hud_area_*.png: a replay too, the viewer's hints
bottom right), so it did not change from April to October. Not seen yet:
the viewer paused, fast-forwarded, in another camera, in its menus, or with its hints hidden (「非表示」, which may hide
the mark too); the recording plays straight through.

The mark is told by its pattern, not by its colour alone (a team's ink can be magenta, and the map's × and the HUD's
pin icon share the corner): work/templates/replay_mark.png marks the box's magenta (128) and the icon's white (255)
inside REGION. A frame scores the least of
  - the correlation of its green channel with that pattern (the magenta has almost no green, the white all of it;
    a fade to white or black changes both alike, so the correlation stays),
  - the green contrast icon - box, over 60 (the mark ~200, a washed-out one 60-120; flat backgrounds ~0),
  - the box's magenta: min(R - G, B - G) of its median colour, over 40 (the mark ~140).
Measured 2026-11-13: the replay recording (every frame of the playback, 5.2-207.7 s) scores >= 0.86 on 98 % of them
and 0.99 typically, lower only inside the fades (below THR: 89 of 12 150 frames, around 8.5 s, 19 s and 202 s). Live
matches score at most 0.38 (pink / magenta ink with a highlight in the corner): 7 025 frames sampled every 0.5 s through
the recordings 2026-10-28_22-51-57, 2026-10-28_23-06-42, 2026-10-29_22-02-57, 2026-11-04_22-52-52, 2026-11-04_22-59-07,
1 556 saved screens of samples/matches (rule / result / medals / judge, max 0.13), 81 frames of work/frames (0.15) and
4 860 tiles of samples/misses scaled up from 480x270 (0.31). The open map (frames/0082_map_open.png, its × in the
corner) scores -0.37.

    python work/replay.py FRAME.png [...]          # print the score and its parts
"""
import cv2, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from weapon_icons import imread_u                      # cv2.imread cannot open a path with non-ASCII characters (a user's folder)

TPL_PATH = os.path.join(os.path.dirname(__file__), 'templates', 'replay_mark.png')
REGION = (28, 116, 36, 152)              # y0, y1, x0, x1: the mark (x 46-140, y 38-105) with a margin; the template's size
THR = 0.6                                # replay frames 0.86-1.0 (98 % of them; a fade lower), live-match frames <= 0.38 (above)
CHEAP_CONTRAST = 20                      # replay_mark: a mean green contrast below this is no mark, without the full score
_tpl = []


def pattern():
    """-> (magenta pixels, white pixels, the white indicator over both, zero mean and unit length)"""
    if not _tpl:
        t = imread_u(TPL_PATH, 0)
        mag, wh = t == 128, t == 255; sel = mag | wh
        p = wh[sel].astype(np.float32); p -= p.mean(); p /= np.linalg.norm(p)
        _tpl.append((mag, wh, sel, p, mag.astype(np.uint8), wh.astype(np.uint8)))
    return _tpl[0]


def parts(f):
    """-> (correlation, green contrast, magenta) of the mark's region"""
    mag, wh, sel, p = pattern()[:4]
    y0, y1, x0, x1 = REGION
    c = f[y0:y1, x0:x1]
    g = c[..., 1].astype(np.float32)
    v = g[sel]; v = v - v.mean(); n = float(np.linalg.norm(v))
    corr = float(v @ p) / n if n > 1e-3 else 0.0
    gm, gw = float(np.median(g[mag])), float(np.median(g[wh]))
    bm, rm = (float(np.median(c[..., k][mag])) for k in (0, 2))
    return corr, gw - gm, min(rm - gm, bm - gm)


def score(f):
    corr, contrast, magenta = parts(f)
    return min(corr, contrast / 60, magenta / 40)


def replay_mark(f):
    """the replay viewer's mark is on this frame. Cheap exit for nearly every live frame (0.05 ms instead of 0.7):
    the mean green of the icon not CHEAP_CONTRAST above that of the box (the weakest replay frame above THR: 39;
    91 % of the live frames sampled are below). Same answer as score() >= THR on all ~27 000 crops measured"""
    *_, mag8, wh8 = pattern(); y0, y1, x0, x1 = REGION; c = f[y0:y1, x0:x1]
    if cv2.mean(c, mask=wh8)[1] - cv2.mean(c, mask=mag8)[1] < CHEAP_CONTRAST: return False
    return score(f) >= THR


if __name__ == '__main__':
    for path in sys.argv[1:]:
        f = imread_u(path, cv2.IMREAD_COLOR)
        corr, contrast, magenta = parts(f)
        print(f'{path}: score {score(f):.3f} (correlation {corr:.2f}, contrast {contrast:.0f}, magenta {magenta:.0f})')
