"""Parse the post-match result screen (1080p): weapons, points, kills/deaths/specials, self row, win/lose, paint %.

Digits are read with glyph templates learnt from labelled frames (build_glyphs), not with OCR:
the font is fixed, so connected components of the white text are normalised and matched.
"""
import glob, cv2, numpy as np, os, json, sys
sys.path.insert(0, os.path.dirname(__file__))
from weapon_match import load_main_weapons, match as match_weapon, RESULT_ROWS, UNKNOWN_BELOW
from signatures import signature, Library

ROOT = os.path.join(os.path.dirname(__file__), '..')
GLYPH_DIR = os.path.join(ROOT, 'assets', 'glyphs')
GLYPH_SIZE = (16, 24)  # w, h after normalisation

# regions relative to a row's y (RESULT_ROWS value = icon top)
POINTS = (8, 48, 1320, 1445)     # dy0, dy1, x0, x1  big digits + 'p'
STATS = (30, 48, 1455, 1660)     # small 'x' + 2 digits, three groups
STAT_X = [(1465, 1525), (1530, 1590), (1595, 1655)]
NAME = (5, 45, 1110, 1320)      # player name band: only its raw signature is used (recorder: killfeed -> result row); names are not identified
ARROW = (0, 45, 925, 985)
WEAPON = (-15, 55, 1040, 1130)
PCT_L = (235, 285, 925, 1120); PCT_R = (235, 285, 1520, 1710)
# banner (top right): white text on black tags, left-aligned at a fixed origin (measured identical on every stored
# result screen, live and video). x, y = top-left of the text, h = its height; the text is read from a fixed canvas
# `w` px wide, so a stray bright pixel of the stage photo cannot shift it (an earlier bounding-box crop did).
# pad = rows of the tag's top padding: where they stop being black the tag ends and the canvas is cut there.
BANNER = {'mode': dict(x=841, y=48, h=18, w=140, pad=(41, 47)),      # "レギュラーマッチ" tag: x 825-975
          'rule': dict(x=837, y=89, h=31, w=200, pad=None),          # "ナワバリバトル": its tag runs on into the stage name
          'stage': dict(x=1061, y=96, h=23, w=280, pad=(86, 92))}    # the tag ends 1190-1315 depending on the name
BANNER_SCALE = 0.5               # signature = the canvas mask at half resolution
BANNER_MIN_W = 40                # px: narrower white is no text (the shortest banner text, バイガイ亭, is 86 px wide; an 8 px
                                 # speck once became an unlabelled "stage" s_da06710c that no screen showed, 2026-10-18)
BANNER_THR = 0.85                # same text on another screen correlates >= 0.99, the closest different stage names 0.61
HOLES = {'0': 1, '6': 1, '9': 1, 'p': 1, '8': 2}               # enclosed holes of the row glyphs (others 0): every labelled glyph
HOLE_SETS = ('big', 'small', 'panel_big', 'panel_small')        # has them. The mean templates alone read small 08 as 06 / 00
                                 # (101 rows of the stored scoreboards, 11 panels) and 06 as 08 (2026-10-29)
STAGE_SHORT_RULE = 56            # px: the stage name follows the rule name in its tag, so after a 5-character rule (ガチヤグラ;
                                 # ガチエリア / ガチアサリ: about there, see STAGE_SHIFT) it starts 56 px left of where it does after ナワバリバトル / ガチホコバトル
STAGE_SHIFT = range(-2, 9)       # px around stage_x where the stage name is looked up: the rule name's width moves it by a few px
                                 # (after ガチアサリ it starts at 1011, 6 px right of ガチヤグラ's 1005, after ガチエリア half a px right) and 1 px off already drops
                                 # the signature from 1.0 to ~0.88, 2 px to ~0.64 (2026-10-29_22-02-57: バイガイ亭 read as a new stage)


def white_mask(bgr, thr=170):
    """1 where every channel is above thr: the same as (bgr.min(axis=2) > thr).astype(np.uint8), ~10x faster"""
    return cv2.inRange(bgr, (int(thr) + 1,) * 3, (255,) * 3) & 1


def bright_mask(bgr, thr):
    """1 where any channel is above thr: the same as (bgr.max(axis=2) > thr).astype(np.uint8)"""
    return (cv2.inRange(bgr, (0, 0, 0), (int(thr),) * 3) == 0).astype(np.uint8)


def dark_share(bgr, below):
    """share of the pixels whose brightest channel is below `below`: the same as (bgr.max(axis=2) < below).mean(),
    ~20x faster (numpy's max over a 3-long axis took 16 ms on the result panel, every frame)"""
    m = cv2.inRange(bgr, (0, 0, 0), (below - 1,) * 3)
    return cv2.countNonZero(m) / m.size


def glyph_boxes(mask, min_h, max_h, min_w=3):
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = [tuple(stats[i][:4]) for i in range(1, n) if min_h <= stats[i][3] <= max_h and stats[i][2] >= min_w]
    return sorted(boxes)  # left to right


def norm_glyph(mask, box):
    x, y, w, h = box
    g = mask[y:y + h, x:x + w] * 255
    return cv2.resize(g, GLYPH_SIZE, interpolation=cv2.INTER_AREA).astype(np.float32) / 255


def holes(mask, box):
    """enclosed background regions of a glyph (8: 2; 0 / 6 / 9 / p: 1)"""
    x, y, w, h = box
    n, _ = cv2.connectedComponents(1 - np.pad(mask[y:y + h, x:x + w], 1), connectivity=4)
    return n - 2                                               # minus the label 0 (the glyph) and the outside


def merge_boxes(boxes, gap=2):
    """merge components that overlap horizontally (e.g. '%' pieces, '.' near digits stay separate)"""
    out = []
    for b in boxes:
        if out and b[0] <= out[-1][0] + out[-1][2] + gap and abs(b[1] - out[-1][1]) < 30:
            x0 = min(out[-1][0], b[0]); y0 = min(out[-1][1], b[1])
            x1 = max(out[-1][0] + out[-1][2], b[0] + b[2]); y1 = max(out[-1][1] + out[-1][3], b[1] + b[3])
            out[-1] = (x0, y0, x1 - x0, y1 - y0)
        else:
            out.append(b)
    return out


class Glyphs:
    def __init__(self, path=GLYPH_DIR):
        self.sets = {}
        for p in glob.glob(os.path.join(path, '*.json')):     # big / small / pct (result screen), timer (HUD)
            d = json.load(open(p, encoding='utf-8'))
            self.sets[os.path.basename(p)[:-5]] = {k: np.array(v, np.float32) for k, v in d.items()}
        self._z = {}

    def zset(self, which):
        """(characters, their templates as rows, mean-free and of unit length): a glyph's Pearson correlation with
        every template is then one matrix product (np.corrcoef per template took ~3 ms per HUD timer read)"""
        tpl = self.sets[which]
        if which not in self._z or self._z[which][0] is not tpl:
            T = np.array([t.ravel() for t in tpl.values()], np.float64); T -= T.mean(axis=1, keepdims=True)
            self._z[which] = tpl, list(tpl), T / np.linalg.norm(T, axis=1, keepdims=True)
        return self._z[which][1:]

    def read(self, mask, boxes, which):
        chars, T = self.zset(which)  # the % bar uses a heavier font than the rows, so it has its own set
        out = ''; scores = []
        for b in boxes:
            g = norm_glyph(mask, b).ravel().astype(np.float64); g -= g.mean()
            idx = range(len(chars))
            if which in HOLE_SETS:                             # only the characters with as many holes, if any
                n = holes(mask, b); idx = [i for i, ch in enumerate(chars) if HOLES.get(ch, 0) == n] or idx
            with np.errstate(invalid='ignore', divide='ignore'):   # a flat glyph: nan, like np.corrcoef
                sc = np.clip(T[idx] @ g / np.linalg.norm(g), -1, 1)
            i = int(np.argmax(sc)); out += chars[idx[i]]; scores.append(round(float(sc[i]), 2))
        return out, scores


def crop(f, r, y=0):
    return f[y + r[0]:y + r[1], r[2]:r[3]]


def tag_end(f, x, pad, x_max):
    """first column >= x where the black tag is over (the padding rows above the text are no longer dark)"""
    dark = (f[pad[0]:pad[1], x:x_max].max(axis=2) < 60).mean(axis=0)
    for i in range(0, len(dark) - 5):
        if dark[i:i + 5].mean() < 0.5: return x + i
    return x_max


def banner_text(band):
    """white, unsaturated px of a banner band (the text; the stage photo around the tags is colourful)"""
    return ((band.min(axis=2) > 190) & ((band.max(axis=2).astype(int) - band.min(axis=2).astype(int)) < 40)).astype(np.uint8)


def stage_x(f):
    """where the stage name starts: told by the gap between the rule name and it (no text in the ~40 px before it)"""
    b = BANNER['stage']; band = banner_text(f[b['y']:b['y'] + b['h'], :])
    for x in (b['x'], b['x'] - STAGE_SHORT_RULE):
        if not band[:, x - 31:x - 5].any(): return x
    return b['x']


def banner_signature(f, kind, x=None):
    """kind = 'mode' / 'rule' / 'stage' -> fixed-size float vector (None when there is no text). Every text of a kind
    is laid on the same canvas, so the same text always gives the same vector and different texts differ wherever
    their glyphs differ; identified with signatures.Library like the medal names (banner_identify). x: where the stage
    name starts (default stage_x)"""
    b = BANNER[kind]; y, h, w = b['y'], b['h'], b['w']
    x = (stage_x(f) if x is None else x) if kind == 'stage' else b['x']
    x1 = x + w if b['pad'] is None else min(x + w, tag_end(f, x, b['pad'], x + w + 40) - 3)
    if x1 - x < BANNER_MIN_W: return None                     # no dark tag there (2026-09-12_23-20-07: the band came out -3 px)
    m = banner_text(f[y - 1:y + h + 1, x:x1])
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    for i in range(1, n):
        if stats[i][4] < 12: m[lab == i] = 0
    cols = np.flatnonzero(m.any(axis=0))
    if m.sum() < 20 or not len(cols) or cols[-1] - cols[0] + 1 < BANNER_MIN_W: return None
    canvas = np.zeros((h + 2, w), np.uint8); canvas[:, :m.shape[1]] = m * 255
    return cv2.resize(canvas, None, fx=BANNER_SCALE, fy=BANNER_SCALE, interpolation=cv2.INTER_AREA).astype(np.float32).ravel() / 255


def banner_identify(f, kind, lib, add_unknown=True):
    """(id, label, score) of a banner text in the library. The stage name is looked up at every start in STAGE_SHIFT
    and the best match counts; a stage name that matches nowhere is added (add_unknown) as read from stage_x"""
    if kind != 'stage': return lib.identify(banner_signature(f, kind), kind, add_unknown=add_unknown, thr=BANNER_THR)
    x = stage_x(f); best = (None, None, 0.0)
    for d in STAGE_SHIFT:
        r = lib.identify(banner_signature(f, kind, x + d), kind, add_unknown=False, thr=BANNER_THR)
        if r[0] is not None and r[2] > best[2]: best = r
    if best[0] is not None or not add_unknown: return best
    return lib.identify(banner_signature(f, kind, x), kind, thr=BANNER_THR)


def row_glyphs(f, y):
    pm = white_mask(crop(f, POINTS, y)); pb = merge_boxes(glyph_boxes(pm, 22, 45))
    sm = white_mask(crop(f, STATS, y)); sb = glyph_boxes(sm, 9, 19)
    return pm, pb, sm, sb


def read_banners(f, lib, add_unknown=True):
    """{stage, stage_id, mode, mode_id, rule, rule_id} of the banner; add_unknown: a text the library does not know is
    added to it (unlabelled), else it reads as None"""
    out = {}
    for key in ('stage', 'mode', 'rule'):
        sid, label, _ = banner_identify(f, key, lib, add_unknown=add_unknown)
        out[key] = label; out[key + '_id'] = sid
    return out


def parse(f, icons, glyphs, lib=None, add_unknown=True):
    """lib: signature library (stage / mode / rule) to use; the store owns it and nothing is saved here.
    add_unknown=False: an unknown banner text is not added to lib (the recorder adds it with read_banners once the
    screen proved to be a real result screen: a frame of the panel still sliding in reads parts of two lines,
    2026-11-10_00-38-55 left m_f51c054f / r_394ad5e6 that way).
    Player names are not read: the killfeed matching in the recorder uses the raw name signature of each row instead."""
    lib = lib or Library()
    res = {'rows': []}
    res.update(read_banners(f, lib, add_unknown))
    for label, y in RESULT_ROWS.items():
        pm, pb, sm, sb = row_glyphs(f, y)
        pts, pts_sc = glyphs.read(pm, pb, 'big')
        st, st_sc = glyphs.read(sm, sb, 'small')
        # split small glyphs into the three stat groups by x
        groups = ['', '', '']
        for b, ch in zip(sb, st):
            ax = STATS[2] + b[0]
            for gi, (x0, x1) in enumerate(STAT_X):
                if x0 <= ax <= x1: groups[gi] += ch
        arrow = crop(f, ARROW, y); yellow = ((arrow[..., 2] > 180) & (arrow[..., 1] > 180) & (arrow[..., 0] < 100)).mean()
        wp = match_weapon(crop(f, WEAPON, y), icons)
        score, name, stage = wp[0][0], wp[0][1], wp[0][2]
        known = score >= UNKNOWN_BELOW and stage != 'variant'             # 'variant': a weapon without a template yet
        res['rows'].append(dict(row=label, team='win' if label.startswith('win') else 'lose', self=bool(yellow > 0.05),
                                weapon=name if known else None, weapon_score=score, weapon_conf=wp[0][3], weapon_stage=stage,
                                weapon_unknown=None,                       # the unknown icon group, set by the recorder (harvest_icons)
                                weapon_alt=wp[1][1] if len(wp) > 1 else None, weapon_candidates=[w[1] for w in wp[:3]],
                                points=pts.rstrip('p'), kills=groups[0].lstrip('x'), deaths=groups[1].lstrip('x'), specials=groups[2].lstrip('x'),
                                min_glyph_score=min([sc for sc, ch in zip(pts_sc + st_sc, pts + st) if ch not in 'xp'] or [None])))
    for side, r in (('pct_left', PCT_L), ('pct_right', PCT_R)):
        m = white_mask(crop(f, r)); b = merge_boxes(glyph_boxes(m, 6, 45))
        res[side] = glyphs.read(m, b, 'pct')[0]
    self_rows = [r for r in res['rows'] if r['self']]
    res['self_result'] = self_rows[0]['team'] if self_rows else None
    return res


def seed_labels(frames, lib):
    """label the signature library from the hand-read stages of the reference frames"""
    for k in GT_STAGE:
        for kind, name in (('stage', GT_STAGE[k]), ('mode', 'レギュラーマッチ'), ('rule', 'ナワバリバトル')):
            sid, _, _ = lib.identify(banner_signature(frames[k], kind), kind, thr=BANNER_THR); lib.label(sid, name)
    lib.save()


# ---------------------------------------------------------------- glyph training
def build_glyphs(labelled, out=GLYPH_DIR, pct_labelled=None):
    """labelled: list of (frame, {'rows': [(row_label, points_str_with_p, 'x06', 'x04', 'x04'), ...], 'pct': (left, right)})
    pct_labelled: frames used for the % glyphs (defaults to `labelled`; only 5 glyphs per frame so use more)"""
    acc = {'big': {}, 'small': {}, 'pct': {}}
    def add(which, mask, boxes, text):
        if len(boxes) != len(text):
            print(f'  [{which}] glyph count {len(boxes)} != len({text!r}) - skipped'); return
        for b, ch in zip(boxes, text):
            acc[which].setdefault(ch, []).append(norm_glyph(mask, b))
    for f, gt in labelled:
        for row, pts, k, d, s in gt['rows']:
            y = RESULT_ROWS[row]; pm, pb, sm, sb = row_glyphs(f, y)
            add('big', pm, pb, pts); add('small', sm, sb, k + d + s)
    for f, gt in (pct_labelled or labelled):
        if gt['pct'] is None: continue                         # ガチルール: counts there, no %
        for r, text in ((PCT_L, gt['pct'][0]), (PCT_R, gt['pct'][1])):
            m = white_mask(crop(f, r)); b = merge_boxes(glyph_boxes(m, 6, 45)); add('pct', m, b, text)
    os.makedirs(out, exist_ok=True)
    for which, d in acc.items():
        json.dump({k: np.mean(v, axis=0).tolist() for k, v in d.items()}, open(os.path.join(out, which + '.json'), 'w', encoding='utf-8'))
        print(which, {k: len(v) for k, v in d.items()})


GT = {
    'v1m1': {'rows': [('win1', '1230p', 'x06', 'x04', 'x04'), ('win2', '1039p', 'x06', 'x02', 'x03'), ('win3', '713p', 'x00', 'x00', 'x03'), ('win4', '616p', 'x01', 'x06', 'x01'),
                      ('lose1', '1058p', 'x03', 'x01', 'x03'), ('lose2', '942p', 'x07', 'x03', 'x02'), ('lose3', '754p', 'x02', 'x02', 'x02'), ('lose4', '596p', 'x03', 'x04', 'x01')], 'pct': ('54.4%', '38.3%')},
    'v1m2': {'rows': [('win1', '936p', 'x01', 'x05', 'x03'), ('win2', '672p', 'x05', 'x02', 'x02'), ('win3', '669p', 'x01', 'x00', 'x02'), ('win4', '372p', 'x00', 'x03', 'x01'),
                      ('lose1', '904p', 'x01', 'x02', 'x04'), ('lose2', '633p', 'x03', 'x01', 'x02'), ('lose3', '605p', 'x01', 'x02', 'x02'), ('lose4', '564p', 'x06', 'x01', 'x02')], 'pct': ('45.7%', '44.3%')},
    'v1m3': {'rows': [('win1', '1056p', 'x05', 'x02', 'x03'), ('win2', '867p', 'x02', 'x04', 'x03'), ('win3', '543p', 'x01', 'x05', 'x01'), ('win4', '489p', 'x07', 'x01', 'x01'),
                      ('lose1', '785p', 'x06', 'x04', 'x02'), ('lose2', '664p', 'x04', 'x03', 'x01'), ('lose3', '470p', 'x06', 'x04', 'x00'), ('lose4', '417p', 'x03', 'x03', 'x01')], 'pct': ('68.0%', '26.3%')},
    'v2m1': {'rows': [('win1', '1232p', 'x03', 'x02', 'x05'), ('win2', '1225p', 'x04', 'x01', 'x04'), ('win3', '1203p', 'x02', 'x02', 'x04'), ('win4', '869p', 'x02', 'x00', 'x02'),
                      ('lose1', '1407p', 'x03', 'x03', 'x05'), ('lose2', '1295p', 'x01', 'x01', 'x04'), ('lose3', '952p', 'x02', 'x00', 'x04'), ('lose4', '692p', 'x01', 'x04', 'x01')], 'pct': ('55.6%', '41.9%')},
    'v2m2': {'rows': [('win1', '1585p', 'x04', 'x00', 'x06'), ('win2', '1033p', 'x04', 'x02', 'x03'), ('win3', '766p', 'x06', 'x00', 'x02'), ('win4', '762p', 'x07', 'x04', 'x01'),
                      ('lose1', '1165p', 'x03', 'x03', 'x03'), ('lose2', '1071p', 'x01', 'x05', 'x04'), ('lose3', '977p', 'x02', 'x00', 'x03'), ('lose4', '478p', 'x01', 'x05', 'x01')], 'pct': ('30.9%', '65.0%')},
    'r1640': {'rows': [('win1', '965p', 'x05', 'x04', 'x04'), ('win2', '869p', 'x01', 'x04', 'x02'), ('win3', '817p', 'x06', 'x05', 'x03'), ('win4', '565p', 'x05', 'x02', 'x01'),
                       ('lose1', '959p', 'x07', 'x04', 'x01'), ('lose2', '740p', 'x02', 'x02', 'x02'), ('lose3', '726p', 'x04', 'x02', 'x02'), ('lose4', '655p', 'x06', 'x05', 'x01')], 'pct': ('50.1%', '46.7%')},
}
GT['live1'] = {'rows': [('win1', '1077p', 'x05', 'x03', 'x02'), ('win2', '1074p', 'x07', 'x05', 'x03'), ('win3', '914p', 'x01', 'x02', 'x03'), ('win4', '882p', 'x09', 'x02', 'x03'),
                        ('lose1', '1438p', 'x05', 'x02', 'x05'), ('lose2', '966p', 'x02', 'x04', 'x02'), ('lose3', '956p', 'x04', 'x04', 'x02'), ('lose4', '487p', 'x05', 'x08', 'x00')], 'pct': ('52.0%', '45.2%')}
# ガチルール (2026-10-28_22-51-57.mp4 / 2026-10-28_23-06-42.mp4): live1 held the only small 8 and 9, so 08 read as 06 / 00
GT['hoko1'] = {'rows': [('win1', '1760p', 'x12', 'x04', 'x08'), ('win2', '1062p', 'x07', 'x05', 'x02'), ('win3', '727p', 'x04', 'x05', 'x04'), ('win4', '1071p', 'x07', 'x05', 'x03'),
                        ('lose1', '1023p', 'x09', 'x05', 'x04'), ('lose2', '1229p', 'x07', 'x05', 'x02'), ('lose3', '1145p', 'x11', 'x05', 'x05'), ('lose4', '701p', 'x09', 'x05', 'x03')], 'pct': None}
GT['yagura2'] = {'rows': [('win1', '1449p', 'x14', 'x03', 'x06'), ('win2', '1061p', 'x12', 'x06', 'x03'), ('win3', '1807p', 'x10', 'x07', 'x06'), ('win4', '1495p', 'x06', 'x07', 'x05'),
                          ('lose1', '1222p', 'x10', 'x06', 'x03'), ('lose2', '1622p', 'x06', 'x05', 'x06'), ('lose3', '1220p', 'x13', 'x06', 'x04'), ('lose4', '1243p', 'x09', 'x14', 'x04')], 'pct': None}
GT['yagura3'] = {'rows': [('win1', '1161p', 'x13', 'x03', 'x05'), ('win2', '1855p', 'x09', 'x04', 'x05'), ('win3', '821p', 'x07', 'x10', 'x03'), ('win4', '1329p', 'x09', 'x06', 'x04'),
                          ('lose1', '1046p', 'x10', 'x07', 'x03'), ('lose2', '1287p', 'x05', 'x08', 'x04'), ('lose3', '2151p', 'x08', 'x08', 'x08'), ('lose4', '1064p', 'x08', 'x07', 'x04')], 'pct': None}
# ガチエリア (2026-11-04_22-59-07.mp4): the first ガチエリア result screen
GT['area1'] = {'rows': [('win1', '1748p', 'x11', 'x03', 'x08'), ('win2', '1641p', 'x07', 'x04', 'x06'), ('win3', '1263p', 'x08', 'x08', 'x05'), ('win4', '1170p', 'x07', 'x03', 'x05'),
                        ('lose1', '1502p', 'x09', 'x05', 'x05'), ('lose2', '1719p', 'x08', 'x07', 'x06'), ('lose3', '2102p', 'x05', 'x05', 'x05'), ('lose4', '881p', 'x03', 'x04', 'x05')], 'pct': None}
GT_STAGE = {'v1m1': 'コンブトラック', 'v1m2': 'ユノハナ大渓谷', 'v1m3': 'ユノハナ大渓谷', 'v2m1': 'ユノハナ大渓谷', 'v2m2': 'ユノハナ大渓谷', 'r1640': 'タラポートショッピングパーク', 'live1': 'スメーシーワールド'}
GT_WEAPON = {'v1m1': ['プロモデラーMG', 'カーボンローラーANGL', 'スプラシューター', 'スプラローラー', 'N-ZAP85', 'ハイドラント圧', 'スクイックリンα', 'リッター4K'],
             'r1640': [None, 'プロモデラーMG', None, '4Kスコープ', None, 'リッター4K', 'リッター4K', None]}


if __name__ == '__main__':
    frames = {k: cv2.imread(os.path.join(ROOT, 'work', 'frames', 'results', k + '.png')) for k in GT}
    train = ['v1m1', 'v1m2', 'v1m3', 'live1']
    if '--build' in sys.argv:
        build_glyphs([(frames[k], GT[k]) for k in train], pct_labelled=[(frames[k], GT[k]) for k in GT])
    glyphs = Glyphs(); icons = load_main_weapons(); lib = Library()
    if '--build' in sys.argv:
        seed_labels(frames, lib)
    for k in GT:
        r = parse(frames[k], icons, glyphs, lib)
        bad = 0
        for row, gt in zip(r['rows'], GT[k]['rows']):
            exp = (gt[1].rstrip('p'), gt[2][1:], gt[3][1:], gt[4][1:])
            got = (row['points'], row['kills'], row['deaths'], row['specials'])
            bad += got != exp
            if got != exp or '-v' in sys.argv:
                print(f'  {k} {row["row"]}: got {got} expected {exp}  weapon={row["weapon"]}')
        pct_ok = GT[k]['pct'] is None or (r['pct_left'], r['pct_right']) == GT[k]['pct']
        print(f'{k} [{"train" if k in train else "test"}]: rows wrong {bad}/8, pct {"ok" if pct_ok else (r["pct_left"], r["pct_right"])}, self={r["self_result"]}, stage={r["stage"]}, {r["mode"]}/{r["rule"]}')
    lib.save()
