"""ガチルール counts (1080p): 'N カウント' or 'ノックアウト!' per team, and the teams' 'Np', on the judge screen and on
the scoreboard. Seen in ガチホコ (2026-10-28_22-51-57.mp4); ナワバリ shows the paint % in the same places (work/judge.py).

Judge screen (ジャッジくん): the bar at the bottom is from my team's point of view (left = mine). Big white text
'68カウント' (digits 68 px, y 861-931, in the font of the judge's % so its 'judge' glyphs read them at 0.98-1.00; the
katakana start ~16 px lower) or 'ノックアウト!' (the side that knocked out), left text from x 162, right text up to x 1757;
under it the team points '340p' (digits 39 px, y 957-996, then a lower 'p'). Both count up from 0 for ~4 s; the
points move smoothly (31カウント with 158p), the final ones were 5 x the count every time (KO = 500p). WIN! / LOSE...
comes while the final numbers show, so the frames with the label vote, as for the % (recorder.judge_summary).

Scoreboard: the header bar (y 244-272) holds the same per team, left = my team, in the scoreboard's % font ('pct'
glyphs: 0 at 0.89); the WIN! and LOSE... rows end with the team points '500 p' (digits y 338-364 / 692-718, 'pct'
glyphs: 0 at 0.88-0.93, 5 at 0.81). Only 0 and 5 were seen there so far; the judge screen is the cross-check.

    python work/counts.py FRAME.png [...]                 # print what is read
    python work/counts.py --build VIDEO FROM TO [...]     # the 'judge_p' glyphs from judge count-ups
    python work/counts.py --templates JUDGE_KO.png SCOREBOARD_KO.png   # cut the ノックアウト! templates
"""
import cv2, json, numpy as np, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from weapon_icons import imread_u                      # cv2.imread cannot open a path with non-ASCII characters (a user's folder)
from result_parser import Glyphs, GLYPH_DIR, white_mask, glyph_boxes, merge_boxes, norm_glyph

TPL_DIR = os.path.join(os.path.dirname(__file__), 'templates')
# judge screen: (y0, y1, x0, x1) per side
J_BIG = {'my': (850, 945, 150, 960), 'enemy': (850, 945, 960, 1775)}
J_PTS = {'my': (948, 1003, 150, 520), 'enemy': (948, 1003, 1400, 1775)}
# scoreboard
S_HDR = {'left': (232, 288, 925, 1320), 'right': (232, 288, 1320, 1712)}
S_PTS = {'win': (330, 372, 1500, 1700), 'lose': (686, 728, 1500, 1700)}
KO_THR = 0.7                       # ノックアウト! template score on the white mask
_tpl = {}


def ko_template(kind):
    if kind not in _tpl: _tpl[kind] = imread_u(os.path.join(TPL_DIR, f'ko_{kind}.png'), 0)
    return _tpl[kind]


def knocked_out(m, kind):
    t = ko_template(kind)
    if t is None or m.shape[0] < t.shape[0] or m.shape[1] < t.shape[1]: return False
    return float(cv2.matchTemplate(m * 255, t, cv2.TM_CCOEFF_NORMED).max()) >= KO_THR


def score(g, v):
    with np.errstate(invalid='ignore', divide='ignore'):          # a solid box (no variance) has no correlation: 0
        return float(np.nan_to_num(np.corrcoef(g.ravel(), v.ravel())[0, 1]))


def best(m, b, tpl):
    """-> (char, score) of the best glyph in the set"""
    g = norm_glyph(m, b)
    return max(((k, score(g, v)) for k, v in tpl.items()), key=lambda kv: kv[1])


def count_before_katakana(m, boxes, tpl, digit_h, min_score):
    """the number right before 'カウント': a run of digit boxes (height digit_h, a sure digit glyph) followed by a box
    that starts lower and is a bit shorter (the katakana). The '.' of a ナワバリ '45.7%' also starts lower but is far
    shorter. None when there is no such run"""
    run = []
    for b in boxes:
        ch, sc = best(m, b, tpl)
        if digit_h[0] <= b[3] <= digit_h[1] and ch.isdigit() and sc >= min_score:
            if run and b[0] - (run[-1][0][0] + run[-1][0][2]) > 25: run = []
            run.append((b, ch)); continue
        last = run[-1][0] if run else None
        if last and b[1] >= last[1] + 5 and b[3] >= 0.6 * last[3] and b[0] - (last[0] + last[2]) <= 25 and len(run) <= 3:
            return int(''.join(ch for _, ch in run))
        run = []
    return None


def points_before_p(m, boxes, tpl, digit_h, min_score):
    """'340p' / '500 p': the digit boxes before the last box, which is the lower 'p'. None unless all read surely"""
    if len(boxes) < 2: return None
    p, digits = boxes[-1], [b for b in boxes[:-1] if digit_h[0] <= b[3] <= digit_h[1]]
    if not digits or p[1] < digits[-1][1] + 5 or not 1 <= len(digits) <= 3 or p[0] - (digits[-1][0] + digits[-1][2]) > 25: return None
    reads = [best(m, b, tpl) for b in digits]
    if any(not ch.isdigit() or sc < min_score for ch, sc in reads): return None
    return int(''.join(ch for ch, _ in reads))


def side_boxes(f, r, thr=190):
    m = white_mask(f[r[0]:r[1], r[2]:r[3]], thr)
    return m, merge_boxes(glyph_boxes(m, 8, r[1] - r[0]))


def read_judge_counts(f, glyphs):
    """-> {'my': dict(count, ko, points), 'enemy': ...}; count = the number, 100 for the side that knocked out (ko=True);
    any value None when not read. All None on a ナワバリ judge screen (no 'カウント' after the digits; it has an 'Np'
    under the % too, which is not read here: a side's points are kept only with its count)"""
    out = {}
    tp = glyphs.sets.get('judge_p') or glyphs.sets['points']
    for side in ('my', 'enemy'):
        m, b = side_boxes(f, J_BIG[side])
        ko = knocked_out(m, 'judge')
        count = 100 if ko else count_before_katakana(m, b, glyphs.sets['judge'], (60, 76), 0.9)
        if count is None: out[side] = dict(count=None, ko=None, points=None); continue
        m, b = side_boxes(f, J_PTS[side])
        out[side] = dict(count=count, ko=ko, points=points_before_p(m, b, tp, (35, 44), 0.8))
    return out


def read_scoreboard_counts(f, glyphs):
    """-> dict(left=dict(count, ko), right=..., win_points, lose_points); left = my team. Values None when not read; the
    rows' points only with a count in the header (a ナワバリ scoreboard has an 'N p' on its rows too, not read here)"""
    out = {}
    for side in ('left', 'right'):
        m, b = side_boxes(f, S_HDR[side])
        ko = knocked_out(m, 'scoreboard')
        count = 100 if ko else count_before_katakana(m, b, glyphs.sets['pct'], (24, 32), 0.8)
        out[side] = dict(count=count, ko=ko if count is not None else None)
    counted = out['left']['count'] is not None or out['right']['count'] is not None
    for row in ('win', 'lose'):
        m, b = side_boxes(f, S_PTS[row])
        out[f'{row}_points'] = points_before_p(m, b, glyphs.sets['pct'], (22, 30), 0.75) if counted else None
    return out


def build_glyphs(video, ranges, out=os.path.join(GLYPH_DIR, 'judge_p.json')):
    """the 'judge_p' glyph set (the judge screen's team points) from every frame of recorded count-ups: each side is
    labelled by reading it with the HUD's paint-point glyphs ('points', same font, but its 5 scores only ~0.57), and kept
    only when the same reading shows on at least 2 frames (a digit in motion reads differently each frame)"""
    tpl = Glyphs().sets['points']; cap = cv2.VideoCapture(video); seen = {}
    for t_from, t_to in ranges:
        cap.set(cv2.CAP_PROP_POS_MSEC, t_from * 1000)
        while True:
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000; ok, f = cap.read()
            if not ok or t > t_to: break
            for side in ('my', 'enemy'):
                m, b = side_boxes(f, J_PTS[side])
                if len(b) < 2 or b[-1][1] < b[-2][1] + 5: continue
                digits = [x for x in b[:-1] if 35 <= x[3] <= 44]
                if not 1 <= len(digits) <= 3 or len(digits) != len(b) - 1: continue
                text = ''.join(best(m, x, tpl)[0] for x in digits)
                if text.isdigit(): seen.setdefault(text, []).append([norm_glyph(m, x) for x in digits])
    acc = {}
    for text, gl in seen.items():
        if len(gl) < 2: continue
        for g in gl:
            for ch, v in zip(text, g): acc.setdefault(ch, []).append(v)
    json.dump({k: np.mean(v, axis=0).tolist() for k, v in sorted(acc.items())}, open(out, 'w', encoding='utf-8'))
    print(out, {k: len(v) for k, v in sorted(acc.items())})


def cut_templates(judge_path, scoreboard_path):
    """ノックアウト! masks: from the left side of a judge frame and of a scoreboard where my team knocked out"""
    for kind, p, r in (('judge', judge_path, J_BIG['my']), ('scoreboard', scoreboard_path, S_HDR['left'])):
        m = white_mask(cv2.imread(p)[r[0]:r[1], r[2]:r[3]], 190)
        b = []
        for x in merge_boxes(glyph_boxes(m, 8, r[1] - r[0])):          # the word: boxes from the left, up to the first wide gap
            if b and x[0] - (b[-1][0] + b[-1][2]) > 30: break
            b.append(x)
        x0 = min(x for x, *_ in b); y0 = min(y for _, y, *_ in b)
        x1 = max(x + w for x, _, w, _ in b); y1 = max(y + h for _, y, _, h in b)
        cv2.imwrite(os.path.join(TPL_DIR, f'ko_{kind}.png'), m[y0:y1, x0:x1] * 255)
        print(kind, (x0 + r[2], y0 + r[0], x1 - x0, y1 - y0))


if __name__ == '__main__':
    if sys.argv[1] == '--build':
        a = sys.argv[3:]; build_glyphs(sys.argv[2], [(float(a[i]), float(a[i + 1])) for i in range(0, len(a), 2)])
    elif sys.argv[1] == '--templates':
        cut_templates(sys.argv[2], sys.argv[3])
    else:
        G = Glyphs()
        for p in sys.argv[1:]:
            f = cv2.imread(p)
            print(p, 'judge', read_judge_counts(f, G), 'scoreboard', read_scoreboard_counts(f, G))
