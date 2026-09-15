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
STAGE = (85, 130, 1040, 1250)    # right part of the banner: stage name
MODE = (40, 75, 825, 980)        # "レギュラーマッチ"
RULE = (85, 130, 825, 1035)      # "ナワバリバトル"


def white_mask(bgr, thr=170):
    return (bgr.min(axis=2) > thr).astype(np.uint8)


def glyph_boxes(mask, min_h, max_h, min_w=3):
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = [tuple(stats[i][:4]) for i in range(1, n) if min_h <= stats[i][3] <= max_h and stats[i][2] >= min_w]
    return sorted(boxes)  # left to right


def norm_glyph(mask, box):
    x, y, w, h = box
    g = mask[y:y + h, x:x + w] * 255
    return cv2.resize(g, GLYPH_SIZE, interpolation=cv2.INTER_AREA).astype(np.float32) / 255


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

    def read(self, mask, boxes, which):
        tpl = self.sets[which]  # the % bar uses a heavier font than the rows, so it has its own set
        out = ''; scores = []
        for b in boxes:
            g = norm_glyph(mask, b)
            best = max(tpl.items(), key=lambda kv: float(np.corrcoef(g.ravel(), kv[1].ravel())[0, 1]))
            out += best[0]; scores.append(round(float(np.corrcoef(g.ravel(), best[1].ravel())[0, 1]), 2))
        return out, scores


def crop(f, r, y=0):
    return f[y + r[0]:y + r[1], r[2]:r[3]]


def row_glyphs(f, y):
    pm = white_mask(crop(f, POINTS, y)); pb = merge_boxes(glyph_boxes(pm, 22, 45))
    sm = white_mask(crop(f, STATS, y)); sb = glyph_boxes(sm, 9, 19)
    return pm, pb, sm, sb


def parse(f, icons, glyphs, lib=None):
    """lib: signature library (stage / mode / rule) to use; the store owns it and nothing is saved here.
    Player names are not read: the killfeed matching in the recorder uses the raw name signature of each row instead."""
    lib = lib or Library()
    res = {'rows': []}
    for key, r in (('stage', STAGE), ('mode', MODE), ('rule', RULE)):
        sid, label, sc = lib.identify(signature(crop(f, r)), key)
        res[key] = label; res[key + '_id'] = sid
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
        res['rows'].append(dict(row=label, team='win' if label.startswith('win') else 'lose', self=bool(yellow > 0.05),
                                weapon=wp[0][1] if wp[0][0] >= UNKNOWN_BELOW else None, weapon_score=wp[0][0], weapon_conf=wp[0][3], weapon_alt=wp[1][1] if len(wp) > 1 else None, weapon_candidates=[w[1] for w in wp[:3]],
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
        sid, _, _ = lib.identify(signature(crop(frames[k], STAGE)), 'stage'); lib.label(sid, GT_STAGE[k])
        sid, _, _ = lib.identify(signature(crop(frames[k], MODE)), 'mode'); lib.label(sid, 'レギュラーマッチ')
        sid, _, _ = lib.identify(signature(crop(frames[k], RULE)), 'rule'); lib.label(sid, 'ナワバリバトル')
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
        pct_ok = (r['pct_left'], r['pct_right']) == GT[k]['pct']
        print(f'{k} [{"train" if k in train else "test"}]: rows wrong {bad}/8, pct {"ok" if pct_ok else (r["pct_left"], r["pct_right"])}, self={r["self_result"]}, stage={r["stage"]}, {r["mode"]}/{r["rule"]}')
    lib.save()
