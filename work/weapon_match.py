"""Identify a weapon icon crop (result screen) against assets/weapon_icons.

Approach (suggested by the user): do not strip the capture's background; instead composite the
reference icon (RGBA) onto the same background colour the capture has behind the icon, then run a
normal colour template match. On the result screen this gives 0.94-0.97 for the right weapon and
separates colour variants (カーボンローラーANGL 0.97 vs デコ 0.90). Icons are 56 px at 1080p.
"""
import cv2, numpy as np, os, json

ROOT = os.path.join(os.path.dirname(__file__), '..')
ICON_DIR = os.path.join(ROOT, 'assets', 'weapon_icons')
SECTIONS = os.path.join(ROOT, 'assets', 'weapon_icons_sections.json')
ICON_PX = 56  # rendered size of the weapon icon on the 1080p result screen
UNKNOWN_BELOW = 0.85  # best natural score under this = icon not in the library (or a different screen); report unknown


def imread_u(p, flags=cv2.IMREAD_UNCHANGED):  # cv2.imread cannot open non-ASCII paths on Windows
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), flags)


REAL_DIR = os.path.join(ROOT, 'assets', 'real_icons', 'result_screen')  # labelled crops for icons the wiki lacks


def icon_name(filename):
    """'.52ガロンデコ.png.webp' -> '.52ガロンデコ' (names may start with a dot, so strip only known extensions)"""
    n = filename
    for ext in ('.webp', '.png'):
        while n.endswith(ext):
            n = n[:-len(ext)]
    return n


def load_main_weapons(size=ICON_PX):
    """RGBA wiki icons resized to `size`, plus labelled real crops (BGR, already on the panel background)
    from assets/real_icons/result_screen/<weapon>.png for weapons missing from the wiki."""
    names = [f for f in json.load(open(SECTIONS, encoding='utf-8'))['ブキ'] if '_フチ' not in f]
    out = {}
    for f in names:
        im = imread_u(os.path.join(ICON_DIR, f))
        if im is None or im.ndim != 3 or im.shape[2] != 4:
            continue
        out[icon_name(f)] = cv2.resize(im, (size, size), interpolation=cv2.INTER_AREA)
    if size == ICON_PX and os.path.isdir(REAL_DIR):
        for f in os.listdir(REAL_DIR):
            im = imread_u(os.path.join(REAL_DIR, f), cv2.IMREAD_COLOR)
            if im is not None and f.endswith('.png'):
                out[f[:-4]] = im  # BGR: matched directly, not composited; overrides a bad wiki icon of the same name
    return out


def score_icon(crop_bgr, im, bg):
    tpl = composited(im, bg)
    if tpl.shape[0] > crop_bgr.shape[0] or tpl.shape[1] > crop_bgr.shape[1]:
        return -1.0
    return float(cv2.matchTemplate(crop_bgr, tpl, cv2.TM_CCOEFF_NORMED).max())


def register_real_icon(crop_bgr, name, icons=None):
    """save the icon area of a result-row crop as a real template for `name` (for weapons the wiki lacks)"""
    crop_bgr = crop_bgr[:, :ICON_PX + 16]  # the player name starts ~70 px into the result-row crop; keep only the icon area
    g = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    ys, xs = np.where(g > 60)
    y0, y1 = max(ys.min() - 2, 0), min(ys.max() + 3, crop_bgr.shape[0]); x0, x1 = max(xs.min() - 2, 0), min(xs.max() + 3, crop_bgr.shape[1])
    patch = crop_bgr[y0:y1, x0:x1]
    os.makedirs(REAL_DIR, exist_ok=True)
    cv2.imencode('.png', patch)[1].tofile(os.path.join(REAL_DIR, name + '.png'))
    if icons is not None:
        icons[name] = patch
    return patch


def composite(rgba, bg):
    a = rgba[..., 3:4].astype(np.float32) / 255
    return (rgba[..., :3] * a + np.asarray(bg, np.float32) * (1 - a)).astype(np.uint8)


def bg_variants(crop_bgr, tol=0, fills=((0, 255, 0), (255, 255, 255))):
    """(image, background) pairs: the crop as-is on its own panel colour, plus copies where pixels that
    match the panel colour are replaced by green / white. The panel is a flat fill, so the match is exact
    (tol=0) on uncompressed frames (live capture, PNG); that keeps the pure-black scope tube of 4Kスコープ
    (luma 0 on a luma-2 panel), which a looser tolerance would wipe out together with the background.
    H.264 recordings smear the near-black levels, so use tol>=2 there and expect scope pairs to be unreliable."""
    g = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    dark = crop_bgr[g < 70]
    bg = np.median(dark.reshape(-1, 3), axis=0).astype(int) if len(dark) else np.zeros(3, int)
    isbg = np.abs(crop_bgr.astype(int) - bg).max(axis=2) <= tol
    out = [(crop_bgr, bg)]
    for fill in fills:
        v = crop_bgr.copy(); v[isbg] = fill; out.append((v, fill))
    return out


def _locate(crop_bgr, rgba, bg):
    r = cv2.matchTemplate(crop_bgr, composite(rgba, bg), cv2.TM_CCOEFF_NORMED)
    y, x = np.unravel_index(r.argmax(), r.shape)
    return int(y), int(x), float(r.max())


def pair_decision(crop_bgr, icons, a, b, tol=2):
    """Decide between two near-identical icons (e.g. リッター4K / 4Kスコープ) by looking only at the pixels where
    their alpha masks differ. Background pixels of the crop are replaced by white so black parts (the scope
    tube, luma 0 on a luma-2 panel) become visible, then the mean absolute residual against each candidate
    (composited on white) is compared inside the difference region. Returns (winner, confidence in 0..1).
    Confidence is (res_loser - res_winner) / (res_loser + res_winner); ~0.13-0.24 on labelled samples."""
    g = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    dark = crop_bgr[g < 70]
    bg = np.median(dark.reshape(-1, 3), axis=0).astype(int) if len(dark) else np.zeros(3, int)
    white = crop_bgr.copy(); white[np.abs(crop_bgr.astype(int) - bg).max(axis=2) <= tol] = (255, 255, 255)
    ia, ib = icons[a], icons[b]; s = ia.shape[0]
    ca, cb = composite(ia, (255, 255, 255)).astype(int), composite(ib, (255, 255, 255)).astype(int)
    diff = cv2.dilate(((ia[..., 3] > 128) != (ib[..., 3] > 128)).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    y0, x0, _ = _locate(crop_bgr, ia, bg)
    best = None
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            y, x = y0 + dy, x0 + dx
            if y < 0 or x < 0 or y + s > white.shape[0] or x + s > white.shape[1]:
                continue
            p = white[y:y + s, x:x + s].astype(int)
            ra = np.abs(p - ca)[diff].mean(); rb = np.abs(p - cb)[diff].mean()
            if best is None or ra + rb < best[0] + best[1]:   # best alignment = smallest total residual
                best = (ra, rb)
    ra, rb = best
    conf = abs(ra - rb) / (ra + rb + 1e-6)
    return (a if ra < rb else b), float(conf)


_COMPOSITES = {}   # (id(icon array), bg) -> icon composited on bg; icons are static so this is filled once per bg colour


def composited(im, bg):
    """cached composite(im, bg) (BGR real crops are returned as-is); the result panel is the same colour on every row,
    so compositing 226 icons per row was a third of the weapon-matching time"""
    if im.shape[2] == 3: return im
    key = (id(im), tuple(int(v) for v in bg))
    tpl = _COMPOSITES.get(key)
    if tpl is None:
        if len(_COMPOSITES) > 4096: _COMPOSITES.clear()
        tpl = _COMPOSITES[key] = composite(im, bg)
    return tpl


def match(crop_bgr, icons, topk=3, close=0.05, tol=2):
    """Stage 1 ranks all icons by the natural-background score. If the runner-up is within `close`
    (a colour/scope variant of the same weapon), stage 2 decides between the top two with pair_decision.
    Returns [(score, name, stage, confidence), ...]: score is always the natural-background score of the
    candidate, confidence is 1.0 for a clear stage-1 win and the pair confidence otherwise."""
    g = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    dark = crop_bgr[g < 70]
    bg = np.median(dark.reshape(-1, 3), axis=0) if len(dark) else np.zeros(3)
    natural = {name: score_icon(crop_bgr, im, bg) for name, im in icons.items()}
    ranked = sorted(natural.items(), key=lambda kv: -kv[1])
    (n1, s1), (n2, s2) = ranked[0], ranked[1]
    if s1 - s2 <= close and icons[n1].shape[2] == 4 and icons[n2].shape[2] == 4:
        winner, conf = pair_decision(crop_bgr, icons, n1, n2, tol=tol)
        loser = n2 if winner == n1 else n1
        return [(round(natural[winner], 3), winner, 'pair', round(conf, 3)), (round(natural[loser], 3), loser, 'pair', round(conf, 3))] +                [(round(s, 3), n, 'natural', None) for n, s in ranked[2:topk]]
    return [(round(s, 3), n, 'natural', 1.0 if i == 0 else None) for i, (n, s) in enumerate(ranked[:topk])]


RESULT_ROWS = {'win1': 390, 'win2': 455, 'win3': 520, 'win4': 585, 'lose1': 745, 'lose2': 810, 'lose3': 875, 'lose4': 940}


def result_screen_weapons(frame, icons):
    return {label: match(frame[y - 15:y + 55, 1040:1130], icons) for label, y in RESULT_ROWS.items()}


if __name__ == '__main__':
    import sys
    icons = load_main_weapons()
    frame = cv2.imread(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'work/frames/0268_result_scoreboard.png'))
    for label, best in result_screen_weapons(frame, icons).items():
        print(label, best)
