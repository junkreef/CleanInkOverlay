"""Identify a weapon icon crop (result screen) against the weapon icon set.

Approach (suggested by the user): do not strip the capture's background; instead composite the
reference icon (RGBA) onto the same background colour the capture has behind the icon, then run a
normal colour template match. On the result screen this gives 0.94-0.97 for the right weapon and
separates colour variants (カーボンローラーANGL 0.97 vs デコ 0.90). Icons are 56 px at 1080p.

Icon set: templates cut from our own result screens (assets/weapon_icons_captured, see weapon_icons.py) first; the wiki
icons (assets/weapon_icons, not redistributable) only for weapons without one. CLEANINK_WEAPON_ICONS=captured|wiki|both
(default both) picks the sets, e.g. `captured` runs as a copy without the wiki icons would.
"""
import cv2, numpy as np, os, json
from weapon_icons import imread_u, without_shadow, crop_bands, ICON_PX, CAPTURED_DIR

ROOT = os.path.join(os.path.dirname(__file__), '..')
ICON_DIR = os.path.join(ROOT, 'assets', 'weapon_icons')
SECTIONS = os.path.join(ROOT, 'assets', 'weapon_icons_sections.json')
UNKNOWN_BELOW = 0.85  # best natural score under this = icon not in the library (or a different screen); report unknown
ICON_SOURCES = ('captured', 'wiki', 'both')


def icon_source():
    s = os.environ.get('CLEANINK_WEAPON_ICONS', 'both')
    if s not in ICON_SOURCES: raise ValueError(f'CLEANINK_WEAPON_ICONS={s!r}: expected one of {ICON_SOURCES}')
    return s


def icon_name(filename):
    """'.52ガロンデコ.png.webp' -> '.52ガロンデコ' (names may start with a dot, so strip only known extensions)"""
    n = filename
    for ext in ('.webp', '.png'):
        while n.endswith(ext):
            n = n[:-len(ext)]
    return n


def load_wiki_icons(size=ICON_PX):
    """RGBA wiki icons of the main weapons resized to `size`; {} when the wiki icons are not installed"""
    if not os.path.exists(SECTIONS) or not os.path.isdir(ICON_DIR): return {}
    names = [f for f in json.load(open(SECTIONS, encoding='utf-8'))['ブキ'] if '_フチ' not in f]
    out = {}
    for f in names:
        im = imread_u(os.path.join(ICON_DIR, f))
        if im is None or im.ndim != 3 or im.shape[2] != 4:
            continue
        out[icon_name(f)] = cv2.resize(im, (size, size), interpolation=cv2.INTER_AREA)
    return out


def load_captured_icons(size=ICON_PX, captured_dir=CAPTURED_DIR):
    """RGBA templates cut from our result screens (56 px); other sizes are for the HUD linking, so they also lose the
    result screen's drop shadow (weapon_icons.without_shadow)"""
    out = {}
    if not os.path.isdir(captured_dir): return out
    for f in os.listdir(captured_dir):
        im = imread_u(os.path.join(captured_dir, f)) if f.endswith('.png') else None
        if im is None or im.ndim != 3 or im.shape[2] != 4: continue
        out[f[:-4]] = im if size == ICON_PX else cv2.resize(without_shadow(im), (size, size), interpolation=cv2.INTER_CUBIC)
    return out


class IconSet(dict):
    """{name: RGBA icon} that also knows which icons are our captured templates (`captured`): only those are checked for
    parts they lack (match's 'variant' stage), the wiki icons are drawn differently"""
    def __init__(self, *a, captured=(), **k):
        super().__init__(*a, **k); self.captured = set(captured)


def load_main_weapons(size=ICON_PX, source=None, captured_dir=CAPTURED_DIR):
    """{weapon name: RGBA icon at `size`}: our captured templates, the wiki icons for the weapons we have none of"""
    source = source or icon_source()
    out = IconSet(load_wiki_icons(size) if source in ('wiki', 'both') else {})
    if source in ('captured', 'both'):
        cap = load_captured_icons(size, captured_dir); out.update(cap); out.captured |= set(cap)
    return out


def score_icon(crop_bgr, im, bg):
    tpl = composited(im, bg)
    if tpl.shape[0] > crop_bgr.shape[0] or tpl.shape[1] > crop_bgr.shape[1]:
        return -1.0
    return float(cv2.matchTemplate(crop_bgr, tpl, cv2.TM_CCOEFF_NORMED).max())


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


SHAPE_TOL = 4       # a crop pixel belongs to the icon's shape when it is this far off the panel colour (0 would do on live
                    # captures, where the panel is exact; 4 also holds on H.264 recordings, 8 starts losing the dark scopes)
SHAPE_OPEN = 3      # the shape difference of two templates is opened by this: a solid part (a scope) stays, 1-2 px fringes go
SHAPE_CLOSE = 0.15  # shape siblings are compared by shape up to this natural-score gap: a dark scope barely moves the colour
                    # score, so リッター4K led 4Kスコープ by 0.05-0.08 on scoped rows
SIBLING_CROSS = 0.9  # ... when the two templates match each other this well (the scope pairs 0.91-0.99; other pairs <= 0.91)
SIBLING_PART = 60    # ... and the part only one of them has is scope-sized (the scope pairs 40-53 px; カーボンローラーANGL / デコ,
                     # the only other pair this alike, 113 px). Looser rules sent replicas and unrelated weapons through
                     # shape_decision, which then guessed (パラシェルター read as オーダーシェルター レプリカ, 2026-10-15)
_SHAPE_REGIONS = {}  # (a, b) -> (icon a, icon b, a's shape, part only b has, part only a has); entries hold the icons, see _COMPOSITES


def _shift(m, dy, dx):
    return np.roll(np.roll(m, dy, 0), dx, 1)


def shape_regions(icons, a, b):
    """the parts that only one of two templates has, after laying b's shape on a's (templates may be framed a few px apart).
    None when they differ only in colour (デコ / colour variants) or one of them is not RGBA."""
    ia, ib = icons[a], icons[b]
    hit = _SHAPE_REGIONS.get((a, b))
    if hit is not None and hit[0] is ia and hit[1] is ib: return hit[2]
    if ia.shape[2] != 4 or ib.shape[2] != 4 or ia.shape != ib.shape: return None
    ma, mb = ia[..., 3] > 0, ib[..., 3] > 0
    _, dy, dx = min((int((ma != _shift(mb, dy, dx)).sum()), dy, dx) for dy in range(-6, 7) for dx in range(-6, 7))
    mb = _shift(mb, dy, dx); k = np.ones((SHAPE_OPEN, SHAPE_OPEN), np.uint8)
    only_b = cv2.morphologyEx((mb & ~ma).astype(np.uint8), cv2.MORPH_OPEN, k) > 0
    only_a = cv2.morphologyEx((ma & ~mb).astype(np.uint8), cv2.MORPH_OPEN, k) > 0
    out = (ma, only_b, only_a) if (only_b.any() or only_a.any()) else None
    if len(_SHAPE_REGIONS) > 1024: _SHAPE_REGIONS.clear()
    _SHAPE_REGIONS[(a, b)] = (ia, ib, out)
    return out


def shape_decision(crop_bgr, icons, a, b):
    """Decide between two icons that differ in shape (リッター4K / 4Kスコープ, スプラチャージャー / スプラスコープ): the panel is one
    flat colour, so everything off it is the icon's shape (the user's idea, 2026-10-15). The scope is drawn a few levels
    above the panel and gets lost in any colour comparison, but as shape it is a solid ~40 px part only one template has.
    The crop's shape is laid on a's template where their common part agrees best; then the share of the crop's shape inside
    each template's own part decides. Returns (winner, confidence = |share_b - share_a| in 0..1) or None (no shape part).
    All 89 stored rows of the five scope pairs but one come out as the scope's brightness says (that one is in doubt)."""
    reg = shape_regions(icons, a, b)
    if reg is None: return None
    ma, only_b, only_a = reg
    g = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY); dark = crop_bgr[g < 70]
    bg = np.median(dark.reshape(-1, 3), axis=0).astype(int) if len(dark) else np.zeros(3, int)
    shape = np.abs(crop_bgr.astype(int) - bg).max(axis=2) > SHAPE_TOL
    y0, x0, _ = _locate(crop_bgr, icons[a], bg); s = ma.shape[0]; own = only_a | only_b; best = None
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            y, x = y0 + dy, x0 + dx
            if y < 0 or x < 0 or y + s > shape.shape[0] or x + s > shape.shape[1]: continue
            w = shape[y:y + s, x:x + s]; miss = int((w != ma)[~own].sum())
            if best is None or miss < best[0]: best = (miss, w)
    w = best[1]
    share_b = w[only_b].mean() if only_b.any() else 0.5
    share_a = w[only_a].mean() if only_a.any() else 0.5
    return (b if share_b > share_a else a), float(abs(share_b - share_a))


VARIANT_PART = 15    # px: a solid part (opened 3x3) of the crop that the matched template lacks, or the other way round, or
VARIANT_COLOUR = 12  # whose colour is off the template's by more than this, means the icon is another weapon that has no
                     # template yet: a variant of the matched one (オーダー レプリカ, デコ, コラボ, a scope). With the right template
                     # left out of the stored rows, 174 of the 203 sibling matches outside the 4K pairs were caught and none of
                     # 1311 right matches tripped it (2026-10-15). The 4K scopes are too dark for SHAPE_TOL; both 4K templates exist.
VARIANT_NEIGHBOURS = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))   # a pixel's own and its 4 neighbours' values count


def extra_parts(crop_bgr, t):
    """(shape px, colour px): solid parts where the crop and template t disagree, tolerant of the rows rendering icons up to
    a pixel apart: a crop pixel only counts against the template's pixel and its 4 neighbours (shape: off the panel colour by
    more than SHAPE_TOL where none of them is, or the other way round; colour: outside their range by more than
    VARIANT_COLOUR; a 3x3 box was too lenient, letting replicas' recoloured stripes through). What is left is opened 3x3;
    the separator bands are left out."""
    g = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY); dark = crop_bgr[g < 70]
    bg = np.median(dark.reshape(-1, 3), axis=0).astype(int) if len(dark) else np.zeros(3, int)
    shape = np.abs(crop_bgr.astype(int) - bg).max(axis=2) > SHAPE_TOL; shape[crop_bands(crop_bgr)] = False
    tc = composite(t, bg); tm = ((t[..., 3] > 0) & (np.abs(tc.astype(int) - bg).max(axis=2) > SHAPE_TOL)).astype(np.uint8)
    k = np.ones((3, 3), np.uint8); nb = VARIANT_NEIGHBOURS
    tm_any, tm_all = cv2.dilate(tm, nb) > 0, cv2.erode(tm, nb) > 0
    t_hi, t_lo = cv2.dilate(tc, nb).astype(int), cv2.erode(tc, nb).astype(int)
    y0, x0, _ = _locate(crop_bgr, t, bg); s = t.shape[0]; best = None
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            y, x = y0 + dy, x0 + dx
            if y < 0 or x < 0 or y + s > shape.shape[0] or x + s > shape.shape[1]: continue
            w = shape[y:y + s, x:x + s]; p = crop_bgr[y:y + s, x:x + s].astype(int)
            sh = int(cv2.morphologyEx(((w & ~tm_any) | (tm_all & ~w)).astype(np.uint8), cv2.MORPH_OPEN, k).sum())
            off = np.maximum(p - t_hi, t_lo - p).max(axis=2)
            col = int(cv2.morphologyEx(((off > VARIANT_COLOUR) & tm_all & w).astype(np.uint8), cv2.MORPH_OPEN, k).sum())
            if best is None or sh + col < sum(best): best = (sh, col)
    return best or (0, 0)


_SIBLINGS = {}       # (a, b) -> (icon a, icon b, bool); entries hold the icons, see _COMPOSITES


def shape_siblings(icons, a, b):
    """two templates that differ only by a scope-sized solid part (SIBLING_CROSS, SIBLING_PART), the case shape_decision
    is for even when the colour score already leads by up to SHAPE_CLOSE"""
    ia, ib = icons[a], icons[b]
    hit = _SIBLINGS.get((a, b))
    if hit is not None and hit[0] is ia and hit[1] is ib: return hit[2]
    reg = shape_regions(icons, a, b); out = False
    if reg is not None and max(reg[1].sum(), reg[2].sum()) <= SIBLING_PART:
        bg = np.full(3, 2)
        pa = cv2.copyMakeBorder(composite(ia, bg), 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=(2, 2, 2))
        pb = cv2.copyMakeBorder(composite(ib, bg), 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=(2, 2, 2))
        cross = min(float(cv2.matchTemplate(pa, composite(ib, bg), cv2.TM_CCOEFF_NORMED).max()),
                    float(cv2.matchTemplate(pb, composite(ia, bg), cv2.TM_CCOEFF_NORMED).max()))
        out = cross >= SIBLING_CROSS
    if len(_SIBLINGS) > 1024: _SIBLINGS.clear()
    _SIBLINGS[(a, b)] = (ia, ib, out)
    return out


def pair_decision(crop_bgr, icons, a, b, tol=2):
    """Decide between two near-identical icons. Icons that differ in shape go to shape_decision; colour variants are decided
    by looking only at the pixels where their alpha masks differ. Background pixels of the crop are replaced by white so black parts (the scope
    tube, luma 0 on a luma-2 panel) become visible, then the mean absolute residual against each candidate
    (composited on white) is compared inside the difference region. Returns (winner, confidence in 0..1).
    Confidence is (res_loser - res_winner) / (res_loser + res_winner); ~0.13-0.24 on labelled samples."""
    by_shape = shape_decision(crop_bgr, icons, a, b)
    if by_shape is not None: return by_shape
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


_COMPOSITES = {}   # (id(icon array), bg) -> (icon array, icon composited on bg); filled once per icon and bg colour.
                   # The entry holds the icon itself: an id is reused once its array is freed (icons reloaded after a new template)


def composited(im, bg):
    """cached composite(im, bg) (BGR real crops are returned as-is); the result panel is the same colour on every row,
    so compositing 226 icons per row was a third of the weapon-matching time"""
    if im.shape[2] == 3: return im
    key = (id(im), tuple(int(v) for v in bg))
    hit = _COMPOSITES.get(key)
    if hit is None or hit[0] is not im:
        if len(_COMPOSITES) > 4096: _COMPOSITES.clear()
        hit = _COMPOSITES[key] = (im, composite(im, bg))
    return hit[1]


def match(crop_bgr, icons, topk=3, close=0.05, tol=2):
    """Stage 1 ranks all icons by the natural-background score. If the runner-up is within `close`
    (a colour/scope variant of the same weapon), or within SHAPE_CLOSE and a shape sibling (scope variant), stage 2
    decides between the top two with pair_decision.
    Returns [(score, name, stage, confidence), ...]: score is always the natural-background score of the
    candidate, confidence is 1.0 for a clear stage-1 win and the pair confidence otherwise. When the winner is one of our
    captured templates (icons.captured) and the crop has a solid part it lacks (extra_parts), the winner's stage is
    'variant': most likely a weapon without a template yet, to be treated as unknown."""
    g = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    dark = crop_bgr[g < 70]
    bg = np.median(dark.reshape(-1, 3), axis=0) if len(dark) else np.zeros(3)
    natural = {name: score_icon(crop_bgr, im, bg) for name, im in icons.items()}
    ranked = sorted(natural.items(), key=lambda kv: -kv[1])
    (n1, s1), (n2, s2) = ranked[0], ranked[1] if len(ranked) > 1 else (None, -1.0)
    if n2 is not None and icons[n1].shape[2] == 4 and icons[n2].shape[2] == 4 and (s1 - s2 <= close or (s1 - s2 <= SHAPE_CLOSE and shape_siblings(icons, n1, n2))):
        winner, conf = pair_decision(crop_bgr, icons, n1, n2, tol=tol)
        loser = n2 if winner == n1 else n1
        out = [(round(natural[winner], 3), winner, 'pair', round(conf, 3)), (round(natural[loser], 3), loser, 'pair', round(conf, 3))] +               [(round(s, 3), n, 'natural', None) for n, s in ranked[2:topk]]
    else:
        out = [(round(s, 3), n, 'natural', 1.0 if i == 0 else None) for i, (n, s) in enumerate(ranked[:topk])]
    w = out[0][1]
    if w in getattr(icons, 'captured', ()) and max(extra_parts(crop_bgr, icons[w])) >= VARIANT_PART:
        out[0] = (out[0][0], w, 'variant', out[0][3])
    return out


RESULT_ROWS = {'win1': 390, 'win2': 455, 'win3': 520, 'win4': 585, 'lose1': 745, 'lose2': 810, 'lose3': 875, 'lose4': 940}


def result_screen_weapons(frame, icons):
    return {label: match(frame[y - 15:y + 55, 1040:1130], icons) for label, y in RESULT_ROWS.items()}


if __name__ == '__main__':
    import sys
    icons = load_main_weapons()
    frame = cv2.imread(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'work/frames/0268_result_scoreboard.png'))
    for label, best in result_screen_weapons(frame, icons).items():
        print(label, best)
