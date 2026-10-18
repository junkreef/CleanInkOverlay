"""Weapon icon templates cut from our own result screens; they replace the wiki icons (assets/weapon_icons), which
may not be redistributed.

    assets/weapon_icons_captured/<weapon>.png   RGBA 56x56 template (shipped): median of the samples, alpha = not panel colour
    data/icon_samples/<weapon>/<stamp>_<row>.png  raw result-row crops (WEAPON box of result_parser, 70x90 BGR), local only

A template has the same framing as a wiki icon resized to 56 px (the size the game renders it at on the result screen), so
weapon_match (composite on the panel colour, pair_decision on the alpha masks) and the HUD linking (masked correlation of
the icon scaled to ~92 px) take it as a drop-in replacement.

Samples are collected without hand labelling: a result row whose icon matched confidently (HARVEST_MIN_SCORE, and for a
colour / scope variant pair HARVEST_MIN_PAIR_CONF) is kept under the matched name until a weapon has MAX_SAMPLES of them,
spread over the row positions (MAX_PER_ROW).
The template is the per-pixel median of its samples, so a one-off disturbance (a mislabelled or damaged sample) drops out
once a weapon has a few; the wiki icon's mask, while it is around, trims anything off the weapon's outline. (The badge in
the bottom-right corner of many icons, e.g. "89" or a brand logo, belongs to the weapon variant and stays.)

Icons that match no template are kept as unknown groups, data/icon_samples/_unknown/<id>/ (library name '_unknown/<id>'):
one group per look, so a weapon seen again joins its group and is named once on the web page (Store.label_weapon_icon),
which moves the samples under the weapon's name. Group templates are rebuilt from the samples on load and never shipped.
A group may carry a guess (GUESS_FILE): icons the wiki icons name with too little confidence to become samples on their
own (UNKNOWN_BELOW <= score < HARVEST_MIN_SCORE) wait there for the user to confirm the wiki's name.
"""
import hashlib, os, re
import cv2, numpy as np

ROOT = os.path.join(os.path.dirname(__file__), '..')
CAPTURED_DIR = os.path.join(ROOT, 'assets', 'weapon_icons_captured')
SAMPLES_DIR = os.path.join(ROOT, 'data', 'icon_samples')
UNKNOWN = '_unknown'
GUESS_FILE = 'guess.txt'  # in a group folder: the weapon the wiki icons took it for
ICON_PX = 56
MAX_SAMPLES = 8
MIN_TO_REPLACE = MAX_SAMPLES  # a shipped template (one without local samples: they are not distributed) is only rebuilt
                         # from local samples once they are complete (spread over >= 4 rows by MAX_PER_ROW): rebuilt from 3,
                         # パラシェルター / スプラローラー / .96ガロン爪 templates no longer matched their other rows (2026-10-15)
MAX_PER_ROW = 2          # samples per result-row position: each of the 8 rows renders the icon a sub-pixel apart, so a
                         # template from one row only matches that row best (リッター4K from lose4 rows read win3 rows as 4Kスコープ)
HARVEST_MIN_SCORE = 0.94
HARVEST_MIN_PAIR_CONF = 0.1
BG_TOL = 1               # live captures are lossless: the panel is exactly (2, 2, 2); the icons' black drop shadow is 2 levels off it
ICON_BOX = (0, 70, 8, 84)  # y0, y1, x0, x1 inside a row crop where the icon can be (left: squid portrait, right: name)
BAND_FILL = 0.9          # a row this full of non-panel pixels is the separator band above / below the black row panel
                         # (the panel starts 12-15 px into the crop depending on the row, so a 56 px window can reach it)
HUD_DARK = 24            # for the HUD copy: pixels darker than this are the result screen's drop shadow / dark fringe


def imread_u(p, flags=cv2.IMREAD_UNCHANGED):  # cv2.imread cannot open non-ASCII paths on Windows
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), flags)


def imwrite_u(p, im):
    cv2.imencode('.png', im)[1].tofile(p)


def panel_bg(crop_bgr):
    g = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    dark = crop_bgr[g < 70]
    return np.median(dark.reshape(-1, 3), axis=0).astype(int) if len(dark) else np.zeros(3, int)


def foreground(im_bgr, bg, tol=BG_TOL):
    return np.abs(im_bgr.astype(int) - bg).max(axis=2) > tol


def band_rows(fg):
    """rows of a foreground mask over the crop's width (ICON_BOX columns, 76 px) that are (almost) entirely foreground: the
    separator bands. Only on that width: a long icon (スピナー) fills 90 % of a 56 px window row, never of 76 px."""
    return fg.mean(axis=1) > BAND_FILL


def crop_bands(crop_bgr):
    """band_rows of a result-row crop, indexed by crop row"""
    _, _, x0, x1 = ICON_BOX
    return band_rows(foreground(crop_bgr[:, x0:x1], panel_bg(crop_bgr)))


def icon_window(crop_bgr, teacher=None):
    """(y, x) of the 56x56 icon window in a result-row crop. teacher = RGBA icon of the same weapon (wiki icon or a
    template): the window is centred on where it matches. Without one, it is centred on the foreground's bounding box
    inside ICON_BOX (the framing may then differ from the wiki's by a few px; the matchers slide, so only the scale matters)."""
    bg = panel_bg(crop_bgr)
    h, w = crop_bgr.shape[:2]
    if teacher is not None:
        a = teacher[..., 3:4].astype(np.float32) / 255
        tpl = (teacher[..., :3] * a + bg.astype(np.float32) * (1 - a)).astype(np.uint8)
        r = cv2.matchTemplate(crop_bgr, tpl, cv2.TM_CCOEFF_NORMED)
        y, x = np.unravel_index(r.argmax(), r.shape)
        cy, cx = y + teacher.shape[0] / 2, x + teacher.shape[1] / 2
    else:
        y0, y1, x0, x1 = ICON_BOX
        fg = foreground(crop_bgr[y0:y1, x0:x1], bg); fg[band_rows(fg)] = False
        ys, xs = np.where(fg)
        if not len(ys): return None
        cy, cx = y0 + (ys.min() + ys.max() + 1) / 2, x0 + (xs.min() + xs.max() + 1) / 2
    y, x = int(round(cy - ICON_PX / 2)), int(round(cx - ICON_PX / 2))
    return min(max(y, 0), h - ICON_PX), min(max(x, 0), w - ICON_PX)


def build_template(crops, teacher=None, trim=None):
    """RGBA 56x56 template from result-row crops of one weapon: per-pixel median of the windows aligned on `teacher`,
    alpha = differs from the panel colour. trim = the weapon's wiki icon (RGBA 56; the windows are aligned on it or on a
    template that was): the alpha is limited to its mask grown by 2 px, which removes stray pixels off the weapon when
    there are too few samples for the median to do it."""
    wins, bgs, bands = [], [], np.zeros(ICON_PX, bool)
    for c in crops:
        yx = icon_window(c, teacher)
        if yx is None: continue
        y, x = yx; wins.append(c[y:y + ICON_PX, x:x + ICON_PX]); bgs.append(panel_bg(c))
        bands |= crop_bands(c)[y:y + ICON_PX]                     # a band edge caught at the top / bottom of a window
    if not wins: return None
    med = np.median(np.stack(wins), axis=0).astype(np.uint8)
    bg = np.median(np.stack(bgs), axis=0).astype(int)
    alpha = foreground(med, bg)
    alpha[bands] = False
    if trim is not None:
        alpha &= cv2.dilate((trim[..., 3] > 0).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    out = np.dstack([med, (alpha * 255).astype(np.uint8)])
    out[~alpha, :3] = bg                                        # transparent pixels carry the panel colour, not noise
    return out


def without_shadow(t):
    """a template for the HUD linking: the result screen draws a black drop shadow and a dark fringe around the icon that the
    HUD (icon over the team-coloured squid) does not have, so they leave the mask, and the edge is eroded by 1 px.
    On the 2026-10-11 sample the team-level gap between the right and the next best slot assignment went from 0.08 / 0.69
    (template as is) to 0.63 / 0.93 (wiki icons: 0.88 / 1.11)."""
    t = t.copy()
    t[t[..., :3].max(axis=2) < HUD_DARK, 3] = 0
    t[..., 3] = cv2.erode(t[..., 3], np.ones((3, 3), np.uint8))
    return t


def group_name(gid):
    return f'{UNKNOWN}/{gid}'


def group_id(name):
    """'_unknown/u1a2b3c4d' -> 'u1a2b3c4d'; None for a weapon name"""
    return name[len(UNKNOWN) + 1:] if name and name.startswith(UNKNOWN + '/') else None


class IconLibrary:
    """templates + their samples. add_sample() collects in memory and rebuilds the template; save() writes both
    (Store owns the instance and calls save, like the signature library). `version` counts template changes, so a holder
    of loaded icon sets (the recorder) knows when to reload them."""

    def __init__(self, captured_dir=CAPTURED_DIR, samples_dir=SAMPLES_DIR):
        self.captured_dir, self.samples_dir = captured_dir, samples_dir
        self.templates = {}
        if os.path.isdir(captured_dir):
            for f in os.listdir(captured_dir):
                if f.endswith('.png'):
                    im = imread_u(os.path.join(captured_dir, f))
                    if im is not None and im.ndim == 3 and im.shape[2] == 4: self.templates[f[:-4]] = im
        self.pending = {}           # name -> [(file stem, crop)] not written yet
        self.dirty = set()          # names whose template changed (or was dropped) since the last save
        self.dropped = set()        # sample files to delete on save
        self.version = 0
        self.shipped = {n for n in self.templates if not self.sample_stems(n)}   # templates made elsewhere (see MIN_TO_REPLACE)
        self.guesses = {}           # group id -> the wiki's name for it, if any
        gdir = os.path.join(samples_dir, UNKNOWN)
        for gid in sorted(os.listdir(gdir)) if os.path.isdir(gdir) else []:
            t = build_template(self.samples(group_name(gid)))
            if t is not None: self.templates[group_name(gid)] = t
            g = os.path.join(gdir, gid, GUESS_FILE)
            if os.path.exists(g): self.guesses[gid] = open(g, encoding='utf-8').read().strip() or None

    def sample_stems(self, name):
        d = os.path.join(self.samples_dir, name)
        disk = [f[:-4] for f in sorted(os.listdir(d)) if f.endswith('.png') and os.path.join(d, f) not in self.dropped] if os.path.isdir(d) else []
        return disk + [s for s, _ in self.pending.get(name, [])]

    def samples(self, name):
        d = os.path.join(self.samples_dir, name)
        disk = [imread_u(os.path.join(d, s + '.png'), cv2.IMREAD_COLOR) for s in self.sample_stems(name) if os.path.exists(os.path.join(d, s + '.png'))]
        return [c for c in disk if c is not None] + [c for _, c in self.pending.get(name, [])]

    def sample(self, name, stem):
        """one sample crop of `name` (pending or on disk)"""
        for s, c in self.pending.get(name, []):
            if s == stem: return c
        return imread_u(os.path.join(self.samples_dir, name, stem + '.png'), cv2.IMREAD_COLOR)

    def groups(self):
        """ids of the unknown groups"""
        return sorted(group_id(n) for n in self.templates if group_id(n))

    def new_group(self, crop, stem, guess=None):
        """start an unknown group with this crop (guess: the wiki's name for it, to be confirmed); returns its id"""
        gid = 'u' + hashlib.md5(crop.tobytes()).hexdigest()[:8]
        self.add_sample(group_name(gid), crop, stem)
        if guess: self.guesses[gid] = guess
        return gid

    def guess(self, gid):
        return self.guesses.get(gid)

    def label_group(self, gid, name, wiki=None):
        """an unknown group turned out to be `name`: its samples move there (as many as `name` still wants, the rest are
        dropped) and the group goes away. wiki = the weapon's wiki icon, if any. Returns the number of samples moved."""
        g = group_name(gid)
        if g not in self.templates: raise KeyError(gid)
        moved = 0
        for stem in list(self.sample_stems(g)):
            moved += self.drop_sample(g, stem, to=name, wiki_to=wiki)
        self.guesses.pop(gid, None)
        return moved

    def wants(self, name, stem=None):
        """True while `name` collects samples; with the sample's stem, also False when its row position is full"""
        if not name or name == UNKNOWN: return False
        stems = self.sample_stems(name)
        if len(stems) >= MAX_SAMPLES: return False
        row = row_of(stem) if stem else None
        return row is None or sum(row_of(s) == row for s in stems) < MAX_PER_ROW

    def add_sample(self, name, crop, stem, wiki=None):
        """keep a result-row crop of `name` and rebuild its template. wiki = the weapon's wiki icon (RGBA 56) while it is
        still around: it aligns the first sample and trims stickers. Returns True when the template changed."""
        if not self.wants(name, stem) or stem in self.sample_stems(name): return False
        self.pending.setdefault(name, []).append((stem, crop.copy()))
        return self.rebuild(name, wiki)

    def rebuild(self, name, wiki=None):
        if name in self.shipped:
            if len(self.sample_stems(name)) < MIN_TO_REPLACE: return False   # keep collecting, keep the shipped template
            self.shipped.discard(name)
        teacher = self.templates.get(name)
        t = build_template(self.samples(name), teacher if teacher is not None else wiki, trim=wiki)
        if t is None: return False
        self.templates[name] = t; self.dirty.add(name); self.version += 1
        return True

    def drop_sample(self, name, stem, to=None, wiki=None, wiki_to=None):
        """take a wrongly labelled sample off `name`; to = the right weapon, which gets it if it still wants samples.
        Rebuilds the templates involved (wiki / wiki_to: their wiki icons, as for add_sample); a weapon left without samples
        loses its template, so the next sample starts it afresh. Returns True when `to` took the sample."""
        items = self.pending.get(name, [])
        hit = next((i for i, (s, _) in enumerate(items) if s == stem), None)
        if hit is not None:
            crop = items.pop(hit)[1]
        else:
            p = os.path.join(self.samples_dir, name, stem + '.png')
            if p in self.dropped or not os.path.exists(p): raise KeyError(f'{name}/{stem}')
            crop = imread_u(p, cv2.IMREAD_COLOR); self.dropped.add(p)
        if self.sample_stems(name): self.rebuild(name, wiki)
        else: self.templates.pop(name, None); self.dirty.add(name); self.version += 1
        return bool(to) and self.add_sample(to, crop, stem, wiki_to)

    def save(self):
        for p in self.dropped:
            if os.path.exists(p): os.remove(p)
        for name, items in self.pending.items():
            d = os.path.join(self.samples_dir, name); os.makedirs(d, exist_ok=True)
            for stem, crop in items: imwrite_u(os.path.join(d, stem + '.png'), crop)
        if self.dirty: os.makedirs(self.captured_dir, exist_ok=True)
        for name in self.dirty:
            if group_id(name):                                    # unknown groups: samples (+ guess) only, never shipped
                d = os.path.join(self.samples_dir, name); g = os.path.join(d, GUESS_FILE); gid = group_id(name)
                if name in self.templates:
                    if self.guesses.get(gid): os.makedirs(d, exist_ok=True); open(g, 'w', encoding='utf-8').write(self.guesses[gid])
                elif os.path.isdir(d):                            # named or emptied: the folder goes
                    if os.path.exists(g): os.remove(g)
                    if not os.listdir(d): os.rmdir(d)
                continue
            p = os.path.join(self.captured_dir, name + '.png')
            if name in self.templates: imwrite_u(p, self.templates[name])
            elif os.path.exists(p): os.remove(p)
        changed = bool(self.pending or self.dirty or self.dropped)
        self.pending, self.dirty, self.dropped = {}, set(), set()
        return changed


def row_of(stem):
    """'2026-10-11_23-18-56_win2' -> 'win2' (None for a sample without a row, e.g. a hand-cut crop)"""
    m = re.search(r'_((?:win|lose)\d)$', stem)
    return m.group(1) if m else None


def lossless(row_crop):
    """live captures keep the panel exactly flat; H.264 recordings smear it, which would turn the alpha into noise"""
    return (np.abs(row_crop.astype(int) - panel_bg(row_crop)).max(axis=2) == 0).mean() > 0.3


def harvestable(row):
    """a parsed result row (result_parser.parse) whose weapon is confident enough to become a sample under its name"""
    return bool(row.get('weapon')) and (row.get('weapon_score') or 0) >= HARVEST_MIN_SCORE and (row.get('weapon_conf') or 0) >= HARVEST_MIN_PAIR_CONF
