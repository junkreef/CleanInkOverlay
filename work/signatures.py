"""Image signatures for fixed-font text we cannot OCR reliably (stage / mode / rule banner, medal names).

A signature is the binarised white text, cropped to its bounding box and resized to 96x16.
Same text on different screens correlates >= 0.81, different text <= 0.39, so a library of labelled
signatures identifies stages/medals without OCR. Unknown signatures are stored with a generated id and
can be named later (label_signature). The recorder also uses raw signatures (no library) to match a
killfeed name against the result rows of the same match.
Player names are no longer collected: kind 'name' entries are dropped when a library is loaded or saved.
"""
import cv2, numpy as np, os, json, hashlib

ROOT = os.path.join(os.path.dirname(__file__), '..')
LIB = os.path.join(ROOT, 'assets', 'signatures.json')
SIZE = (96, 16)
MATCH_THR = 0.6
DROPPED_KINDS = ('name',)     # kinds that were collected once and are ignored / removed now


def signature(bgr, thr=190, max_chroma=40):
    # strict white: bright in every channel and nearly grey, so bright stage photos behind the banner are ignored
    m = ((bgr.min(axis=2) > thr) & ((bgr.max(axis=2).astype(int) - bgr.min(axis=2).astype(int)) < max_chroma)).astype(np.uint8)
    # all of these texts sit on a black tag/row: keep only white pixels that have dark pixels within ~6 px,
    # which drops bright parts of the stage photo around the banner tags
    dark = (bgr.max(axis=2) < 60).astype(np.uint8)
    m &= cv2.dilate(dark, np.ones((13, 13), np.uint8))
    # drop specks (< 12 px): a single stray pixel at the edge would shift the bounding box and the whole signature
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    for i in range(1, n):
        if stats[i][4] < 12:
            m[lab == i] = 0
    ys, xs = np.where(m > 0)
    if len(xs) < 20:
        return None
    m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return cv2.resize(m * 255, SIZE, interpolation=cv2.INTER_AREA).astype(np.float32).ravel() / 255


class Library:
    def __init__(self, path=LIB):
        self.path = path
        items = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}  # id -> {kind, label, sig}
        self.items = {k: it for k, it in items.items() if it.get('kind') not in DROPPED_KINDS}

    def save(self, drop=()):
        """merge with the file first: a label added by another process (e.g. labelling a new stage while the
        recorder runs) must not be overwritten by this process's older in-memory copy. drop = ids being deleted
        on purpose: they are not taken back from the file"""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if os.path.exists(self.path):
            try:
                disk = json.load(open(self.path, encoding='utf-8'))
                for k, it in disk.items():
                    if k in drop or it.get('kind') in DROPPED_KINDS: continue
                    if k not in self.items: self.items[k] = it
                    elif it.get('label') and not self.items[k].get('label'): self.items[k]['label'] = it['label']
            except (OSError, ValueError):
                pass
        json.dump(self.items, open(self.path, 'w', encoding='utf-8'), ensure_ascii=False)

    def identify(self, sig, kind, add_unknown=True, thr=MATCH_THR):
        """returns (id, label_or_None, score); thr = minimum correlation to count as the same text"""
        if sig is None:
            return None, None, 0.0
        best = (None, -1.0)
        for k, it in self.items.items():
            if it['kind'] != kind:
                continue
            c = float(np.corrcoef(sig, np.array(it['sig'], np.float32))[0, 1])
            if c > best[1]:
                best = (k, c)
        if best[0] is not None and best[1] >= thr:
            return best[0], self.items[best[0]]['label'], best[1]
        if not add_unknown:
            return None, None, best[1]
        k = kind[:1] + '_' + hashlib.md5(sig.tobytes()).hexdigest()[:8]
        self.items[k] = {'kind': kind, 'label': None, 'sig': sig.round(3).tolist()}
        return k, None, 1.0

    def label(self, key, label):
        self.items[key]['label'] = label
