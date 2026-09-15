"""表彰 (medal) screen: shown ~3 s right before the scoreboard ("ゲットした表彰" + up to 3 tilted banners).

Layout (1080p): header white text y 384-413 x 868-1016; banner i (i = 0..2) = white box at
(x0, y0) = (960 + 178 i, 444 + 69 i), 380 x 94 px; squid medal icon at (x0 - 48, y0 + 34), 70 x 51 px,
yellow = gold, grey = silver; banner text (dark on white) inside x0+90 .. x0+360, y0+15 .. y0+80.
The text is read as a 96x16 signature (signatures.Library, kind 'medal') so new medal names get an id
and are labelled by hand later, like stage names.

    python work/medals.py FRAME.png [...]     # print what is read from saved frames
"""
import cv2, numpy as np, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from signatures import Library, SIZE

ROOT = os.path.join(os.path.dirname(__file__), '..')
TPL = os.path.join(os.path.dirname(__file__), 'templates', 'medals_header.png')
HEADER = (370, 425, 850, 1040)
PANEL = (440, 700, 900, 1720)
BANNER_W, BANNER_H = 380, 94
MEDAL_THR = 0.85                 # every name ends in 'No.1', so different medals still correlate 0.6-0.76
_tpl = None


def banner_box(i):
    return 960 + 178 * i, 444 + 69 * i


def header_score(f):
    global _tpl
    if _tpl is None:
        _tpl = cv2.imread(TPL, 0)
    m = (f[HEADER[0]:HEADER[1], HEADER[2]:HEADER[3]].min(axis=2) > 200).astype(np.uint8) * 255
    return float(cv2.matchTemplate(m, _tpl, cv2.TM_CCOEFF_NORMED).max())


def looks_like_medals(f):
    pan = f[PANEL[0]:PANEL[1], PANEL[2]:PANEL[3]]
    if (pan.max(axis=2) < 70).mean() < 0.3: return False
    return header_score(f) > 0.8


def banner_present(f, i):
    x0, y0 = banner_box(i)
    b = f[y0 + 5:y0 + BANNER_H - 5, x0 + 100:x0 + 340]
    mn = b.min(axis=2).astype(int); mx = b.max(axis=2).astype(int)
    return ((mn > 150) & (mx - mn < 45)).mean() > 0.5


def medal_rank(f, i):
    x0, y0 = banner_box(i)
    ic = f[y0 + 34:y0 + 85, x0 - 48:x0 + 22]
    yellow = ((ic[..., 2] > 170) & (ic[..., 1] > 170) & (ic[..., 0] < 130)).mean()
    return 'gold' if yellow > 0.15 else 'silver', round(float(yellow), 3)


def banner_signature(f, i):
    x0, y0 = banner_box(i)
    b = f[y0 + 15:y0 + 80, x0 + 90:x0 + 360]
    m = (b.max(axis=2) < 90).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    for k in range(1, n):
        if st[k][4] < 15 or st[k][3] > 40: m[lab == k] = 0
    ys, xs = np.where(m > 0)
    if len(xs) < 40: return None
    m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return cv2.resize(m * 255, SIZE, interpolation=cv2.INTER_AREA).astype(np.float32).ravel() / 255


def parse_medals(f, lib=None):
    """-> list of dict(position, rank, sig_id, name, score) for the banners present (0-3)"""
    lib = lib or Library(); out = []
    for i in range(3):
        if not banner_present(f, i): break
        sig = banner_signature(f, i)
        sid, label, sc = lib.identify(sig, 'medal', thr=MEDAL_THR)
        rank, yel = medal_rank(f, i)
        out.append(dict(position=i, rank=rank, sig_id=sid, name=label, score=round(sc, 3), yellow=yel))
    return out


def build_header_template(frame_path):
    f = cv2.imread(frame_path)
    m = (f[384:413, 868:1016].min(axis=2) > 200).astype(np.uint8) * 255
    cv2.imwrite(TPL, m); print('header template', m.shape)


if __name__ == '__main__':
    if sys.argv[1] == '--build-header':
        build_header_template(sys.argv[2]); sys.exit()
    lib = Library()
    for p in sys.argv[1:]:
        f = cv2.imread(p)
        print(p, 'medals screen' if looks_like_medals(f) else 'NOT a medals screen', round(header_score(f), 2))
        for m in parse_medals(f, lib): print('   ', m)
    lib.save()
