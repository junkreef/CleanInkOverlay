"""In-match HUD readers: timer, slot state (dead / special flash), weapon icon -> result row linking.

    python work/hud.py --build-timer VIDEO T0 T1     # learn timer digit glyphs from a match (HUD start T0 .. finish T1)
    python work/hud.py --test-timer VIDEO T0 T1      # read the timer every 0.5 s and report inconsistencies

HUD layout (1080p): 8 squid slots y 38-112, ally x 527-869, enemy x 1057-1390; timer box y 48-104 x 910-1010.
The rules other than ナワバリ (5:00) have the same squids / timer / killfeed / bubbles, but no paint points top right
(so hud_visible is False there: the recorder asks timer_hud instead), and after 0:00 they can go into overtime, when
the timer box shows 「延長中!」 instead of digits (overtime()).
Each slot carries the player's weapon icon (~92 px, not rotated, full colour) over the team-coloured squid, so a
masked correlation against the team's 4 result-screen weapons links HUD slot <-> result row (8/8 on the sample,
true 0.74-0.97, runner-up <= 0.66). Dead players show a grey silhouette + X instead of the icon.
"""
import cv2, numpy as np, os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
from result_parser import glyph_boxes, merge_boxes, norm_glyph, GLYPH_DIR   # glyph sets: timer (build_timer_glyphs), points (HUD paint points, labelled by hand from clustered glyphs)

SLOT_X = [(527, 597), (622, 692), (711, 781), (799, 869), (1057, 1127), (1145, 1215), (1233, 1303), (1320, 1390)]
SLOT_Y = (38, 112)
TIMER = (48, 104, 905, 1015)
POINTS = (45, 110, 1500, 1690)
OVERTIME = (38, 114, 885, 1035)   # around the timer box: 「延長中!」 in team colours with a black outline, matched by the outline
OVERTIME_THR = 0.6                # the outline template scores 0.89-1.00 over the overtime, <= 0.16 on any other HUD / screen
KILLFEED = (995, 1045, 720, 1200); BUBBLE = (390, 490, 780, 1140); BOTTOM = (975, 1065, 780, 1140); RESPAWN = (960, 1030, 1550, 1910)
ICON_SIZES = (88, 92, 96)


def crop(f, r):
    return f[r[0]:r[1], r[2]:r[3]]


# ---------------------------------------------------------------- timer
def timer_mask(f):
    """digits are white, and yellow-green under 1:00, on a black box: bright = any channel > 170"""
    return (crop(f, TIMER).max(axis=2) > 170).astype(np.uint8)


def timer_glyphs(f):
    m = timer_mask(f)
    return m, merge_boxes(glyph_boxes(m, 15, 50))


def read_timer(f, glyphs):
    """-> (remaining seconds, 'M:SS', min glyph score) or (None, None, 0) when the box does not read as M:SS"""
    m, boxes = timer_glyphs(f)
    if len(boxes) != 3 or 'timer' not in glyphs.sets:
        return None, None, 0.0
    txt, sc = glyphs.read(m, boxes, 'timer')
    if not txt.isdigit():
        return None, None, min(sc)
    rem = int(txt[0]) * 60 + int(txt[1:])
    return rem, f'{txt[0]}:{txt[1:]}', min(sc)


_overtime_tpl = None


def overtime(f):
    """the timer box says 「延長中!」: its black outline matched against work/templates/overtime.png (colour-free: the box
    and letters are in the teams' colours)"""
    global _overtime_tpl
    if _overtime_tpl is None: _overtime_tpl = cv2.imread(os.path.join(os.path.dirname(__file__), 'templates', 'overtime.png'), 0)
    m = ((crop(f, OVERTIME).max(axis=2) < 70) * 255).astype(np.uint8)
    return float(cv2.matchTemplate(m, _overtime_tpl, cv2.TM_CCOEFF_NORMED).max()) >= OVERTIME_THR


def timer_hud(f, glyphs):
    """the HUD of a rule without paint points: the timer box reads as M:SS, or says 「延長中!」 -> (visible, rem, clock)"""
    tv = cv2.cvtColor(crop(f, TIMER), cv2.COLOR_BGR2HSV)[..., 2]
    if 0.55 < (tv < 60).mean() < 0.9:
        rem, clock, _ = read_timer(f, glyphs)
        if rem is not None and int(clock[2:]) < 60: return True, rem, clock   # the map / a jump over the box reads as '7:99', '0:99'...
    return (True, None, None) if overtime(f) else (False, None, None)


def hud_visible(f):
    tv = cv2.cvtColor(crop(f, TIMER), cv2.COLOR_BGR2HSV)[..., 2]
    pts = (crop(f, POINTS).min(axis=2) > 200).mean()
    return 0.55 < (tv < 60).mean() < 0.9 and 0.1 < pts < 0.5


# ---------------------------------------------------------------- slots
def slot_img(f, i, pad=0):
    x0, x1 = SLOT_X[i]
    return f[SLOT_Y[0] - pad:SLOT_Y[1] + pad, x0 - pad:x1 + pad]


def slot_state(f, i):
    """-> dict(dark=fraction of low-sat dark px (dead icon), white=fraction of low-sat bright px (special flash))"""
    hsv = cv2.cvtColor(slot_img(f, i), cv2.COLOR_BGR2HSV); S = hsv[..., 1]; V = hsv[..., 2]; low = S < 50
    return dict(dark=float((low & (V < 120)).mean()), white=float((low & (V >= 205)).mean()))


# ---------------------------------------------------------------- weapon icon linking
def scaled_icon(rgba, size):
    return cv2.resize(rgba, (size, size), interpolation=cv2.INTER_AREA)


def masked_ncc(patch, rgba):
    """max over positions of the normalised correlation between the icon's opaque pixels and the patch.
    cv2.matchTemplate with a mask computes exactly this (TM_CCOEFF_NORMED: mean-subtracted inside the mask);
    the earlier numpy sliding-window version gave identical scores but materialised ~65 MB per call (95 ms)"""
    m = rgba[..., 3] > 127
    if m.sum() < 30: return 0.0
    h, w = m.shape
    if h > patch.shape[0] or w > patch.shape[1]: return 0.0
    tpl = np.ascontiguousarray(rgba[..., :3], dtype=np.float32)
    mask = np.repeat(m[..., None].astype(np.float32), 3, axis=2)
    r = cv2.matchTemplate(np.ascontiguousarray(patch, dtype=np.float32), tpl, cv2.TM_CCOEFF_NORMED, mask=mask)
    return float(np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0).max())


def slot_weapon_scores(f, slot, candidates, icons, pad=28):
    """candidates: {weapon name: RGBA icon (any size)} -> {name: best score over ICON_SIZES}"""
    patch = slot_img(f, slot, pad)
    return {n: max(masked_ncc(patch, scaled_icon(icons[n], s)) for s in ICON_SIZES) for n in candidates if n in icons}


def link_slots(f, team_weapons, icons):
    """team_weapons: {'ally': [4 weapon names in result order], 'enemy': [...]}; names may repeat or be None.
    -> {slot: (best weapon, score, runner-up score)}; scores accumulate over calls if you pass several frames via link_slots_multi"""
    out = {}
    for slot in range(8):
        cands = [w for w in team_weapons['ally' if slot < 4 else 'enemy'] if w]
        sc = slot_weapon_scores(f, slot, set(cands), icons)
        if not sc: out[slot] = (None, 0.0, 0.0); continue
        order = sorted(sc.items(), key=lambda kv: -kv[1])
        out[slot] = (order[0][0], round(order[0][1], 3), round(order[1][1], 3) if len(order) > 1 else 0.0)
    return out


def assign_rows(slot_scores, rows):
    """slot_scores: {slot: {weapon: score}}; rows: result rows (dicts with 'team' ally/enemy, 'weapon').
    Assign each slot a distinct row of its team maximising total score (4! permutations). -> {slot: row index}"""
    import itertools
    link = {}
    for team, slots in (('ally', range(0, 4)), ('enemy', range(4, 8))):
        ris = [i for i, r in enumerate(rows) if r['team'] == team]
        best = None
        for perm in itertools.permutations(ris):
            tot = sum(slot_scores[s].get(rows[ri]['weapon'], 0.0) for s, ri in zip(slots, perm))
            if best is None or tot > best[0]: best = (tot, perm)
        for s, ri in zip(slots, best[1]): link[s] = ri
    return link


# ---------------------------------------------------------------- timer glyph training
def build_timer_glyphs(video, t0, t1, out=GLYPH_DIR, step=1.0):
    """The timer shows 3:00 from HUD start, then counts down once per second: label every glyph from the
    expected value (t_go = first sample whose glyphs differ from the 3:00 glyphs) and average per digit."""
    cap = cv2.VideoCapture(video); fps = cap.get(cv2.CAP_PROP_FPS)
    samples = []
    for sec in np.arange(t0, t1, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(sec * fps))); ok, f = cap.read()
        if not ok: break
        m, boxes = timer_glyphs(f)
        if len(boxes) == 3: samples.append((sec, [norm_glyph(m, b) for b in boxes]))
    ref = samples[0][1]
    def same(a, b): return float(np.corrcoef(a.ravel(), b.ravel())[0, 1]) > 0.9
    i_go = next(i for i, (_, g) in enumerate(samples) if not all(same(x, y) for x, y in zip(g, ref)))
    t_go = samples[i_go][0]; print(f'3:00 from {samples[0][0]:.1f}s, countdown starts at {t_go:.1f}s')
    acc = {}; conflicts = 0
    for sec, g in samples:
        rem = 180 if sec < t_go else max(0, 179 - int(round((sec - t_go) / step)) * int(step))
        txt = f'{rem // 60}{rem % 60:02d}'
        for ch, gl in zip(txt, g): acc.setdefault(ch, []).append(gl)
    # each digit template = mean of its samples; report samples that fit another digit better (labelling errors)
    tpl = {k: np.mean(v, axis=0) for k, v in acc.items()}
    for k, v in acc.items():
        for gl in v:
            best = max(tpl, key=lambda d: float(np.corrcoef(gl.ravel(), tpl[d].ravel())[0, 1]))
            conflicts += best != k
    os.makedirs(out, exist_ok=True)
    json.dump({k: v.tolist() for k, v in tpl.items()}, open(os.path.join(out, 'timer.json'), 'w', encoding='utf-8'))
    print('timer glyphs:', {k: len(v) for k, v in sorted(acc.items())}, 'conflicts:', conflicts)


def test_timer(video, t0, t1, step=0.5):
    from result_parser import Glyphs
    glyphs = Glyphs(); cap = cv2.VideoCapture(video); fps = cap.get(cv2.CAP_PROP_FPS)
    prev = None; bad = 0; n = 0; unread = 0
    for sec in np.arange(t0, t1, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(sec * fps))); ok, f = cap.read()
        if not ok: break
        rem, txt, sc = read_timer(f, glyphs); n += 1
        if rem is None: unread += 1; continue
        if prev is not None and not (0 <= prev[0] - rem <= 2):
            bad += 1; print(f'  jump at {sec:.1f}s: {prev[1]} -> {txt} (score {sc})')
        prev = (rem, txt)
    print(f'{n} samples, {unread} unread, {bad} inconsistent steps; last {prev}')


if __name__ == '__main__':
    if sys.argv[1] == '--build-timer':
        build_timer_glyphs(sys.argv[2], float(sys.argv[3]), float(sys.argv[4]))
    elif sys.argv[1] == '--test-timer':
        test_timer(sys.argv[2], float(sys.argv[3]), float(sys.argv[4]))


def slot_weapon_scores_patch(patch, candidates, icons):
    """same as slot_weapon_scores but for an already-cropped slot patch (slot_img(f, i, 28))"""
    return {n: max(masked_ncc(patch, scaled_icon(icons[n], s)) for s in ICON_SIZES) for n in candidates if n in icons}


# ---------------------------------------------------------------- special gauge (own special only)
GAUGE = (40, 200, 1690, 1870)          # ring gauge top right; centre (90, 80) inside the crop, ring radius 62-84 px
_RING = None


def _ring_mask():
    global _RING
    if _RING is None:
        h, w = GAUGE[1] - GAUGE[0], GAUGE[3] - GAUGE[2]
        yy, xx = np.mgrid[:h, :w]; r = np.sqrt((yy - 80) ** 2 + (xx - 90) ** 2)
        _RING = (r > 62) & (r < 84)
    return _RING


def gauge_state(f):
    """-> (orange, white): fraction of ring pixels that are orange (charging / draining) and white (ready).
    Filling: orange grows 0 -> ~0.38, then the ring turns white (~0.3) while the special is ready.
    Activation: white -> orange ~0.4 in one sample, then orange drains linearly to 0 in ~1.4 s.
    Death: the ring stays as it was (white or orange) until respawn, then shows half (~0.2 orange)."""
    hsv = cv2.cvtColor(crop(f, GAUGE), cv2.COLOR_BGR2HSV); m = _ring_mask()
    H, S, V = hsv[..., 0][m], hsv[..., 1][m], hsv[..., 2][m]
    orange = float(((H >= 5) & (H <= 30) & (S > 120) & (V > 150)).mean())
    white = float(((S < 60) & (V > 200)).mean())
    return orange, white


GAUGE_C = (1780, 120)                  # ring centre (x, y) in the frame
GAUGE_END = 270                        # the segmented ring runs clockwise from 12 o'clock to ~270 deg (22-23 segments, ~12 deg each); the sub icon sits at 300-330
_ARC = None


def gauge_level(f):
    """-> fill 0..1 of the own special gauge: the lit arc (orange while charging / draining, white when ready; unlit
    segments are grey V < 150) runs clockwise from 12 o'clock, so the level is where the lit run starting at 0 deg
    ends, allowing gaps <= 20 deg: 3-6 deg between segments, ~10 deg where the ready ring's pulsing highlight dims a
    segment (8 deg read 1.0 / 0.37 alternately while ready). Per-angle value = median V over radii 64-82."""
    global _ARC
    if _ARC is None:
        ang = np.deg2rad(np.arange(0, 290)); rad = np.arange(64, 84, 2)
        _ARC = (np.rint(GAUGE_C[1] - rad[None, :] * np.cos(ang)[:, None]).astype(int), np.rint(GAUGE_C[0] + rad[None, :] * np.sin(ang)[:, None]).astype(int))
    v = f[_ARC[0], _ARC[1]].max(axis=2)                       # HSV value = max channel
    lit = np.flatnonzero(np.median(v, axis=1) > 150)
    if not len(lit) or lit[0] > 8: return 0.0
    gaps = np.flatnonzero(np.diff(lit) > 20)
    end = lit[gaps[0]] if len(gaps) else lit[-1]
    return round(min(1.0, (end + 1) / GAUGE_END), 3)


PTS_TEXT = (45, 120, 1490, 1700)       # 'NNNNp' own paint points: 4 digit boxes h 50-51 at y 19-21 in this crop, 'p' h 24 at y 50


def read_points(f, glyphs, min_score=0.8):
    """-> (points, min glyph score) or (None, score). The digits roll like an odometer while the count rises: a rolling
    digit is cut / shifted, so the read is only taken when exactly 4 full-height digits are present and all match well."""
    m = (crop(f, PTS_TEXT).min(axis=2) > 200).astype(np.uint8)
    boxes = [b for b in glyph_boxes(m, 46, 56) if 15 <= b[1] <= 25]
    if len(boxes) != 4 or 'points' not in glyphs.sets: return None, 0.0
    txt, sc = glyphs.read(m, boxes, 'points')
    return (int(txt), min(sc)) if min(sc) >= min_score else (None, min(sc))


READY_WHITE = 0.2                      # ring white fraction while the special is ready (0.21-0.27 on the recordings, charging / draining < 0.05)


def special_ready(samples, min_n=2):
    """samples: recorder rows (t, vis, g_wh) -> times the own gauge became ready (first of >= min_n white samples).
    The ready state only ends on a clearly non-white ring (activation, or respawn after dying with it), so a hidden
    HUD (map, death) in between does not produce a second event."""
    out = []; ready = False; run = []
    for r in samples:
        if not r.get('vis') or 'g_wh' not in r: continue
        if r['g_wh'] >= READY_WHITE:
            run.append(r['t'])
            if not ready and len(run) >= min_n: out.append(run[0]); ready = True
        else:
            run = []
            if r['g_wh'] < 0.05: ready = False
    return out


def special_uses(samples, min_gap=3.0):
    """samples: dicts with t, vis, g_or, g_wh (recorder rows) -> times of own special activations
    (white/ready seen within 0.5 s, then orange >= 0.3 with no white). 17/17 on the 5 recorded matches."""
    out = []; last_full = -1e9; last_ev = -1e9
    for r in samples:
        if not r.get('vis') or 'g_wh' not in r: continue
        if r['g_wh'] >= READY_WHITE: last_full = r['t']
        elif r['g_or'] >= 0.3 and r['g_wh'] < 0.05 and 0 < r['t'] - last_full <= 0.5 and r['t'] - last_ev > min_gap:
            out.append(r['t']); last_ev = r['t']
    return out
