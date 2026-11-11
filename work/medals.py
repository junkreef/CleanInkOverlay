"""表彰 (medal) screen: shown ~3 s right before the scoreboard ("ゲットした表彰" + 1-3 tilted banners).

Layout (1080p): header white text y 384-413 x 868-1016. The banners are drawn bigger the fewer there are, so
there is one fixed layout per count (LAYOUTS, measured on stored screens: 3 banners on 87 screens pixel-identical,
2 and 1 on one screen each). The count is read from the white banner boxes, everything else is fixed:
text (dark on white) region, squid medal icon (yellow = gold, grey = silver). The text region is scaled to the
3-banner size and read as a 96x16 signature (signatures.Library, kind 'medal'), so the same name on a 1- or
2-banner screen gives the same signature; new names get an id and are labelled by hand later, like stage names.

    python work/medals.py FRAME.png [...]     # print what is read from saved frames
"""
import cv2, numpy as np, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from signatures import Library
from weapon_icons import imread_u                      # cv2.imread cannot open a path with non-ASCII characters (a user's folder)
from result_parser import dark_share

ROOT = os.path.join(os.path.dirname(__file__), '..')
TPL = os.path.join(os.path.dirname(__file__), 'templates', 'medals_header.png')
HEADER = (370, 425, 850, 1040)
PANEL = (440, 700, 900, 1720)
MEDAL_THR = 0.8                  # over the stored screens the same name scores >= 0.89, the closest different name 0.72
TEXT_SIZE = (315, 65)            # the text region of the 3-banner layout; the other layouts' regions have the same aspect and are resized to it
SIG_SIZE = (192, 32)             # the text's bounding box is resized to this (finer than signatures.SIZE: one glyph can be the whole difference)
DIGIT_SIZE = (24, 24)            # the last glyph ('1' / '2' of "No.1") is appended to the signature at this size, so that
                                 # "塗りポイント No.1" and "No.2" (identical but for that glyph) do not correlate like the same text
_tpl = None

# per banner count: top-left corners of the white banners, their size, and the text / icon regions (dx0, dx1, dy0, dy1) from a corner
LAYOUTS = {3: dict(origins=[(962, 444), (1140, 513), (1318, 582)], box=(378, 92), text=(45, 360, 15, 80), icon=(-48, 22, 34, 85)),
           2: dict(origins=[(958, 457), (1170, 539)], box=(496, 112), text=(90, 470, 20, 98), icon=(-10, 60, 52, 104)),
           1: dict(origins=[(1058, 487)], box=(534, 120), text=(90, 510, 20, 107), icon=(-10, 60, 56, 112))}


def banner_boxes(f):
    """white banner boxes (x, y, w, h) in the panel, top to bottom: their count picks the layout"""
    pan = f[PANEL[0]:PANEL[1], PANEL[2]:PANEL[3]]
    mn = pan.min(axis=2).astype(int); mx = pan.max(axis=2).astype(int)
    m = cv2.morphologyEx(((mn > 190) & (mx - mn < 30)).astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    boxes = [(int(st[i][0]) + PANEL[2], int(st[i][1]) + PANEL[0], int(st[i][2]), int(st[i][3])) for i in range(1, n) if st[i][2] > 250]
    return sorted(boxes, key=lambda b: b[1])


def region(layout, i, key):
    """absolute (x0, x1, y0, y1) of banner i's text / icon region in a layout"""
    x0, y0 = layout['origins'][i]; dx0, dx1, dy0, dy1 = layout[key]
    return x0 + dx0, x0 + dx1, y0 + dy0, y0 + dy1


def header_score(f):
    global _tpl
    if _tpl is None:
        _tpl = imread_u(TPL, 0)
    m = (f[HEADER[0]:HEADER[1], HEADER[2]:HEADER[3]].min(axis=2) > 200).astype(np.uint8) * 255
    return float(cv2.matchTemplate(m, _tpl, cv2.TM_CCOEFF_NORMED).max())


def looks_like_medals(f):
    pan = f[PANEL[0]:PANEL[1], PANEL[2]:PANEL[3]]
    if dark_share(pan, 70) < 0.3: return False
    return header_score(f) > 0.8


def medal_rank(f, layout, i):
    x0, x1, y0, y1 = region(layout, i, 'icon'); ic = f[y0:y1, x0:x1]
    yellow = ((ic[..., 2] > 170) & (ic[..., 1] > 170) & (ic[..., 0] < 130)).mean()
    return 'gold' if yellow > 0.15 else 'silver', round(float(yellow), 3)


def banner_signature(f, layout, i):
    x0, x1, y0, y1 = region(layout, i, 'text')
    b = cv2.resize(f[y0:y1, x0:x1], TEXT_SIZE, interpolation=cv2.INTER_AREA)
    m = (b.max(axis=2) < 90).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    h, w = m.shape; glyphs = []
    for k in range(1, n):
        x, y, gw, gh, area = (int(v) for v in st[k][:5])
        # specks, tall things, and the black background showing at the region's edges beside the tilted banner
        if area < 15 or gh > 40 or ((y == 0 or y + gh == h or x == 0 or x + gw == w) and gw > 40): m[lab == k] = 0
        else: glyphs.append((x, y, gw, gh))
    ys, xs = np.where(m > 0)
    if len(xs) < 40: return None
    text = cv2.resize(m[ys.min():ys.max() + 1, xs.min():xs.max() + 1] * 255, SIG_SIZE, interpolation=cv2.INTER_AREA)
    x, y, gw, gh = max(glyphs, key=lambda g: g[0] + g[2])
    digit = cv2.resize(m[y:y + gh, x:x + gw] * 255, DIGIT_SIZE, interpolation=cv2.INTER_AREA)
    return np.concatenate([text.ravel(), digit.ravel()]).astype(np.float32) / 255


def parse_medals(f, lib=None):
    """-> list of dict(position, rank, sig_id, name, score) for the banners present (0-3)"""
    lib = lib or Library(); out = []
    layout = LAYOUTS.get(len(banner_boxes(f)))
    for i in range(len(layout['origins']) if layout else 0):
        sig = banner_signature(f, layout, i)
        sid, label, sc = lib.identify(sig, 'medal', thr=MEDAL_THR)
        rank, yel = medal_rank(f, layout, i)
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
