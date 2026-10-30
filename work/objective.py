"""ガチヤグラ / ガチホコ: the objective's track under the HUD squids (1080p), read once per second by the recorder.

The track runs along y 155 from my goal (left, a round end in my team's colour at x ~510) to the enemy's (right,
x ~1405); centre x ~958. Dots ~14 px apart: black = ground one of the teams has already covered (from the enemy's
best on the left to mine on the right), my / the enemy's colour beyond. ヤグラ adds square checkpoints on it.
The objective is a ~40 px round icon on the line: white = nobody on it / nobody carries the ホコ, a team's colour =
that team rides / carries it. Team colours change every match, so they are read from the two ends each time.

Positions are given as -100 (my goal) .. 0 (centre) .. +100 (enemy goal). They are positions on the HUD line, not
counts: the line is not drawn to the count's scale (ヤグラ 2026-10-28 #2: best -36 at 40 counts; ホコ #2: +69 at 68),
and the icon also shows where the count does not move (ヤグラ drifting after its rider left, a ホコ carried through
the air that goes back to the last ground when its carrier is splatted).
"""
import cv2, numpy as np

Y = 155; CX = 958; LX = 510; RX = 1405; HALF = (RX - LX) / 2
PITCH = 14                 # px between dots
DOTS_MY = [968 + PITCH * k for k in range(30)]       # dot centres, the same on every ヤグラ / ホコ screen: 30 on my push side
DOTS_ENEMY = [950 - PITCH * k for k in range(30)]    # (centre -> enemy goal) and 30 on the enemy's (centre -> my goal)
ICON_R = (16, 24)          # icon radius
HUE_TOL = 10               # hue steps (of 180) for a dot / the icon to count as a team's colour
OLIVE = (24, 36, 160)      # hue range and max value of the icon's fill when nobody holds it (a yellow team is brighter)
HIDDEN_MAX = 4             # dots in a row that may be hidden (the icon covers 3, a checkpoint 2) inside a black run


def pos(x):
    return round(100.0 * (x - CX) / HALF, 1)


def hsv(px):
    """BGR px (N x 3) -> OpenCV hue (0-180), saturation, value (0-255) arrays"""
    h = cv2.cvtColor(np.asarray(px, np.uint8).reshape(-1, 1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(int)
    return h[:, 0], h[:, 1], h[:, 2]


def end_colours(f):
    """(mine, enemy's) hue from the fills of the two round ends. The dots and the icon carry the same hue, more
    saturated / darker than the ends, so colours are told by hue"""
    a = f[Y - 3:Y + 4, LX - 4:LX + 5].reshape(-1, 3); e = f[Y - 3:Y + 4, RX - 4:RX + 5].reshape(-1, 3)
    return int(np.median(hsv(a)[0])), int(np.median(hsv(e)[0]))


def team(px, hue):
    """mask: px of that team's hue (saturated, not dark)"""
    h, sat, v = hsv(px)
    d = np.abs(h - hue); d = np.minimum(d, 180 - d)
    return (d <= HUE_TOL) & (sat > 100) & (v > 80)


def dot_class(f, x, mine, enemy):
    """'k' black (covered ground), 'a' my colour, 'e' the enemy's, '' something else over the dot (icon, checkpoint, a
    squid, the stage behind): the median of 3x3 px at its centre"""
    c = np.median(f[Y - 1:Y + 2, x - 1:x + 2].reshape(-1, 3), 0)
    if c.max() < 70: return 'k'
    if team([c], mine)[0]: return 'a'
    if team([c], enemy)[0]: return 'e'
    return ''


def reach(f, xs, mine, enemy):
    """index of the last black dot of the run that starts at the centre (dots `xs`, centre outwards), up to HIDDEN_MAX
    unreadable dots in a row allowed inside it; -1 when it does not start there (nobody has pushed that way)"""
    last = -1; hidden = 0
    for i, x in enumerate(xs):
        k = dot_class(f, x, mine, enemy)
        if k == 'k': last = i; hidden = 0
        elif k and (i + 1 == len(xs) or dot_class(f, xs[i + 1], mine, enemy) != 'k'): break   # team colours: the covered ground has ended
        else:                                                                                  # (a lone one is something over the dot)
            hidden += 1
            if hidden > HIDDEN_MAX: break
    return last


def icon(f, mine, enemy):
    """-> (x, holder) of the objective's icon: holder 'my' / 'enemy' (a team's colour fills it; a white emblem sits on
    top) or None (white ring, olive fill: nobody on it); None when not found"""
    g = cv2.cvtColor(f[Y - 30:Y + 31, LX + 20:RX - 20], cv2.COLOR_BGR2GRAY)
    c = cv2.HoughCircles(cv2.medianBlur(g, 3), cv2.HOUGH_GRADIENT, dp=1, minDist=60, param1=120, param2=22, minRadius=ICON_R[0], maxRadius=ICON_R[1])
    if c is None: return None
    for x, y, r in c[0]:
        x = float(x) + LX + 20; y = float(y) + Y - 30
        if abs(y - Y) > 8: continue
        yy, xx = np.mgrid[-int(r):int(r) + 1, -int(r):int(r) + 1]; d = np.hypot(yy, xx); ring = (d > r * .75) & (d < r * .95)
        px = f[np.clip(int(y) + yy[ring], 0, f.shape[0] - 1), np.clip(int(x) + xx[ring], 0, f.shape[1] - 1)]   # the fill around the emblem
        h, sat, v = hsv(px)
        olive = ((h >= OLIVE[0]) & (h <= OLIVE[1]) & (v < OLIVE[2])).mean()
        fm, fe = team(px, mine).mean(), team(px, enemy).mean()
        holder = None if olive > max(fm, fe) else 'my' if fm > .3 and fm > fe else 'enemy' if fe > .3 else None
        return x, holder
    return None


def read(f):
    """-> dict(pos, holder, my_best, enemy_best) on the -100..100 scale (pos / holder None when the icon was not found).
    my_best >= 0 is how far my team has pushed towards the enemy goal, enemy_best >= 0 how far the enemy has pushed
    towards mine: the end of the black run on that side. The pushing team's icon hides the end of its run, so when that
    team holds it just past the last black dot, the icon's centre is the end"""
    mine, enemy = end_colours(f)
    ic = icon(f, mine, enemy)
    out = dict(pos=pos(ic[0]) if ic else None, holder=ic[1] if ic else None)
    for key, xs, who, sign in (('my_best', DOTS_MY, 'my', 1), ('enemy_best', DOTS_ENEMY, 'enemy', -1)):
        i = reach(f, xs, mine, enemy)
        end = xs[i] if i >= 0 else CX
        if ic and ic[1] == who and 0 <= (ic[0] - end) * sign <= PITCH * HIDDEN_MAX: end = ic[0]
        out[key] = max(0.0, pos(end) * sign)
    return out


def present(f):
    """the track is on screen: both round ends filled with a bright, saturated colour, of two different hues (nothing of
    the kind sits there on the ナワバリ / ガチエリア HUDs), and most dots readable. Not by the dots' colours: late in a
    match both teams may have covered nearly the whole line, all black"""
    ends = [np.median(f[Y - 2:Y + 3, x - 2:x + 3].reshape(-1, 3), 0) for x in (LX, RX)]
    h, sat, v = hsv(ends)
    d = abs(int(h[0]) - int(h[1])); d = min(d, 180 - d)
    if not ((sat >= 100) & (v >= 170)).all() or d < 15: return False
    mine, enemy = int(h[0]), int(h[1])
    return sum(dot_class(f, x, mine, enemy) != '' for x in DOTS_MY + DOTS_ENEMY) >= 40
