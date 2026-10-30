"""ガチエリア / ガチアサリ: the two count boxes under the HUD timer (1080p), read once per second by the recorder.

Left = my team, right = the enemy, each 「のこり N」 (the count still to go, 100 at the start). The box of the team that
holds the area(s) and is counting down is filled with its colour, white digits; otherwise it is black with digits in the
team's colour, and a bit smaller. The digits are the timer's font: the 'timer' glyph set reads them (0.75-0.91 on the
2026-10-10 recordings). Between the boxes, one or two zone icons in the colour of whoever has painted them.

Penalty: under a box, a dark pill 「+N」 in white. A team gets it when the other team takes the zones from it (about 3/4
of what it counted during its hold, paid penalty included: 97 -> +74, 36 -> +28, 28 + 14 -> +32 on 2026-10-10). While
that team holds every zone again, the penalty goes down first and 「のこり」 stays; the pill stays while nobody pays.

Counts are given like the judge screen's 「N カウント」: how far a team has got, 100 - のこり.

ガチアサリ has the same boxes, digits and 「+N」 pills (checked on 2026-10-29_22-02-57.mp4, 2 matches): the box is lit
while the team's attack is on (it broke the other goal's barrier; a pie timer between the boxes counts the attack down),
and the pill shows up when that attack ends with counts made (23 -> +11, 54 -> +16) and is paid first on the next one.
Between the boxes one ⚓ (the goal) instead of the zone icons. So the same reader serves both rules: 'holder' is the
team whose attack is on.
"""
import cv2, numpy as np
from result_parser import glyph_boxes

BOX = {'my': (150, 214, 800, 912), 'enemy': (150, 214, 1008, 1130)}   # y0, y1, x0, x1: the digit rows of each box (のこり above y 150)
DIGIT_H = (34, 52); DIGIT_W = (8, 32)
MIN_SCORE = 0.6                   # glyph correlation below this: something over the box (a squid, the map), not read
PEN = {'my': (218, 262, 815, 935), 'enemy': (218, 262, 990, 1110)}    # the 「+N」 pill under each box
PEN_H = (14, 34)


def box(f, side):
    y0, y1, x0, x1 = BOX[side]
    return f[y0:y1, x0:x1]


def state(f, side):
    """'lit' (filled with the team's colour: that team is counting), 'dark' (black box) or None (no box: no area HUD)"""
    hsv = cv2.cvtColor(box(f, side), cv2.COLOR_BGR2HSV)
    s, v = np.median(hsv[..., 1]), np.median(hsv[..., 2])
    if v < 90: return 'dark'
    if v > 150 and s > 80: return 'lit'
    return None


def remaining(f, side, glyphs):
    """the box's 「のこり」 number, or None. Digits: white on a lit box, light (team colour) on a dark one"""
    st = state(f, side)
    if st is None: return None
    hsv = cv2.cvtColor(box(f, side), cv2.COLOR_BGR2HSV); s, v = hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    m = ((v > 110) if st == 'dark' else ((v > 170) & (s < 70))).astype(np.uint8)
    bs = [b for b in glyph_boxes(m, *DIGIT_H, DIGIT_W[0]) if b[2] <= DIGIT_W[1]]
    if not 1 <= len(bs) <= 3: return None
    txt, sc = glyphs.read(m, bs, 'timer')
    if not txt.isdigit() or min(sc) < MIN_SCORE or int(txt) > 100: return None
    return int(txt)


def penalty(f, side, glyphs):
    """the 「+N」 under the box, or None (no pill, or something over it). The '+' is the first glyph: about as wide as high,
    less than half filled. A stray mark after the digits makes 3 digits ('281' for 28): over 100 is not read"""
    y0, y1, x0, x1 = PEN[side]
    hsv = cv2.cvtColor(f[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 2] > 200) & (hsv[..., 1] < 60)).astype(np.uint8)
    bs = glyph_boxes(m, *PEN_H, 3)
    if len(bs) < 2: return None
    x, y, w, h = bs[0]
    if not (m[y:y + h, x:x + w].mean() < .55 and .7 < w / h < 1.4): return None
    txt, sc = glyphs.read(m, bs[1:], 'timer')
    if not txt.isdigit() or min(sc) < MIN_SCORE or int(txt) > 100: return None
    return int(txt)


def read(f, glyphs):
    """-> dict(my_count, enemy_count, holder, my_penalty, enemy_penalty): counts 100 - のこり (None when unread), holder
    'my' / 'enemy' (that team's box is lit) or None, penalties 「+N」 (None: no pill or unread)"""
    rm, re = remaining(f, 'my', glyphs), remaining(f, 'enemy', glyphs)
    sm, se = state(f, 'my'), state(f, 'enemy')
    return dict(my_count=None if rm is None else 100 - rm, enemy_count=None if re is None else 100 - re,
                holder='my' if sm == 'lit' and se != 'lit' else 'enemy' if se == 'lit' and sm != 'lit' else None,
                my_penalty=penalty(f, 'my', glyphs), enemy_penalty=penalty(f, 'enemy', glyphs))


def present(f, glyphs):
    """the area HUD is on screen: both boxes read as a number"""
    return remaining(f, 'my', glyphs) is not None and remaining(f, 'enemy', glyphs) is not None
