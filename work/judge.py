"""ジャッジくん screen: the paint % of both teams on a bar at the bottom, then WIN! / LOSE... top left (1080p).

Shown after Finish! in every ナワバリ match (before the team poses, the 表彰 panel and the scoreboard). When the
scoreboard is skipped (schedule change: the game goes straight back to the lobby) this is the only place left that
says who won and by how much. The % counts up first (~3 s, no label); the label comes ~0.75 s after the final
numbers and stays on with the bar for ~2 s (then on through the team poses, without the bar).

Layout: the bar is from my team's point of view, like the scoreboard's (left = my team, right = the enemy, win or
lose). % digits are white, 68 px high (y 862-931), in the scoreboard's heavy % font but drawn bigger: its 'pct'
glyphs read them right with low scores (~0.7), so they have their own set 'judge' (build_glyphs). Left text starts
at x 166, right text ends at x 1757. The label
(white on a black splash) is told apart by template: WIN! sits at y 61-118, LOSE... at y 70-128.

    python work/judge.py FRAME.png [...]     # print what is read
    python work/judge.py --build WIN.png LOSE.png   # cut the label templates from two frames
    python work/judge.py --glyphs VIDEO FROM TO     # the 'judge' % glyph set from a count-up (2026-10-11_22-14-08.mp4 261.5 268)
"""
import cv2, json, numpy as np, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from result_parser import Glyphs, GLYPH_DIR, white_mask, glyph_boxes, merge_boxes, norm_glyph

TPL_DIR = os.path.join(os.path.dirname(__file__), 'templates')
LABEL = (40, 150, 20, 340)               # y0, y1, x0, x1: search area of the WIN! / LOSE... label
PCT_L = (850, 945, 150, 520); PCT_R = (850, 945, 1400, 1775)
LABEL_THR = 0.7                          # label template score
GLYPH_MIN = 0.7                          # every % glyph must score at least this (a squid or confetti across a digit drops it)
OUTSIDE_MAX = 150                        # white px allowed outside the glyph boxes (confetti specks)
PCT_RE = re.compile(r'^\d{1,3}\.\d%$')
_tpl = {}


def label_templates():
    if not _tpl:
        for k in ('win', 'lose'):
            t = cv2.imread(os.path.join(TPL_DIR, f'judge_{k}.png'), 0)
            if t is not None: _tpl[k] = t
    return _tpl


def label_mask(f):
    y0, y1, x0, x1 = LABEL
    return white_mask(f[y0:y1, x0:x1], 200) * 255


def read_label(f):
    """'win' / 'lose' / None, and the best template score"""
    box = f[LABEL[0]:LABEL[1], LABEL[2]:LABEL[3]]
    if (box.max(axis=2) < 50).mean() < 0.35: return None, 0.0      # no black splash: cheap exit for every other frame
    m = label_mask(f)
    sc = {k: float(cv2.matchTemplate(m, t, cv2.TM_CCOEFF_NORMED).max()) for k, t in label_templates().items()}
    if not sc: return None, 0.0
    k = max(sc, key=sc.get)
    return (k if sc[k] >= LABEL_THR else None), round(sc[k], 3)


def pct_boxes(f, r):
    m = white_mask(f[r[0]:r[1], r[2]:r[3]], 190)
    b = [x for x in merge_boxes(glyph_boxes(m, 10, 75)) if x[3] >= 50 or x[3] <= 20]   # digits / % (66-68 px) and the '.' (16 px)
    return m, b


def covered(m, boxes):
    """white outside the glyph boxes: something bright (a flying squid, a sticker) over the text. One hid the 3 of
    38.3% entirely and the rest read as a clean '8.3%' (0246_result_pct.png), so such a side is not read at all"""
    rest = m.copy()
    for x, y, w, h in boxes: rest[y:y + h, x:x + w] = 0
    return int(rest.sum()) > OUTSIDE_MAX


def read_pct(f, r, glyphs):
    """-> (text, lowest glyph score); ('', 0.0) when something covers the text"""
    m, b = pct_boxes(f, r)
    if covered(m, b): return '', 0.0
    text, sc = glyphs.read(m, b, 'judge')
    return text, min(sc or [0.0])


def read_judge(f, glyphs):
    """-> dict(result='win'|'lose', my_pct, enemy_pct, label_score, glyph_score) or None when this is not the final
    judge screen, or a digit is hidden / misread (each side must read as 'NN.N%' and both sum to <= 100)"""
    res, lsc = read_label(f)
    if res is None: return None
    out = dict(result=res, label_score=lsc)
    for key, r in (('my_pct', PCT_L), ('enemy_pct', PCT_R)):
        text, gsc = read_pct(f, r, glyphs)
        if not PCT_RE.match(text) or gsc < GLYPH_MIN: return None
        out[key] = float(text[:-1]); out['glyph_score'] = min(out.get('glyph_score', 1.0), gsc)
    if out['my_pct'] + out['enemy_pct'] > 100.05: return None
    return out


def build_glyphs(video, t_from, t_to, out=os.path.join(GLYPH_DIR, 'judge.json')):
    """the 'judge' glyph set from every frame of a recorded count-up (both sides count from 0.0% to the final value,
    so all digits show up): each side is labelled by reading it with the scoreboard's 'pct' set, and kept only when
    that reading has the NN.N% shape and the same reading shows on at least 2 frames (a digit in motion or covered
    reads differently each frame)"""
    pct = Glyphs().sets['pct']; cap = cv2.VideoCapture(video); cap.set(cv2.CAP_PROP_POS_MSEC, t_from * 1000)
    seen = {}
    while True:
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000; ok, f = cap.read()
        if not ok or t > t_to: break
        for r in (PCT_L, PCT_R):
            m, b = pct_boxes(f, r)
            if covered(m, b): continue
            text = ''.join('.' if x[3] <= 20 else         # the scoreboard's '.' is a different blob: told by its size here
                           max(((k, v) for k, v in pct.items() if k != '.'), key=lambda kv: float(np.corrcoef(norm_glyph(m, x).ravel(), kv[1].ravel())[0, 1]))[0] for x in b)
            if PCT_RE.match(text): seen.setdefault(text, []).append([norm_glyph(m, x) for x in b])
    acc = {}
    for text, gl in seen.items():
        if len(gl) < 2: continue
        for g in gl:
            for ch, v in zip(text, g): acc.setdefault(ch, []).append(v)
    json.dump({k: np.mean(v, axis=0).tolist() for k, v in sorted(acc.items())}, open(out, 'w', encoding='utf-8'))
    print(out, {k: len(v) for k, v in sorted(acc.items())})


def build(win_path, lose_path):
    for k, p in (('win', win_path), ('lose', lose_path)):
        m = label_mask(cv2.imread(p))
        ys, xs = np.where(m > 0)
        t = m[max(ys.min() - 4, 0):ys.max() + 5, max(xs.min() - 4, 0):xs.max() + 5]
        cv2.imwrite(os.path.join(TPL_DIR, f'judge_{k}.png'), t); print(k, t.shape)


if __name__ == '__main__':
    if sys.argv[1] == '--build': build(sys.argv[2], sys.argv[3]); sys.exit()
    if sys.argv[1] == '--glyphs': build_glyphs(sys.argv[2], float(sys.argv[3]), float(sys.argv[4])); sys.exit()
    g = Glyphs()
    for p in sys.argv[1:]:
        f = cv2.imread(p)
        print(os.path.basename(p), read_label(f), read_pct(f, PCT_L, g), read_pct(f, PCT_R, g), read_judge(f, g))
