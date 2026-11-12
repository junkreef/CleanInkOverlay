"""Scan a video at 2 fps for rule screens (8 player cards) and result screens; save one frame per run.
    python work/scan_screens.py VIDEO OUTDIR
"""
import cv2, numpy as np, sys, os, time
sys.path.insert(0, os.path.dirname(__file__))
from live_result_watch import looks_like_result
from result_parser import dark_share
from rule_screen import CARD_X, card_tops

TAG_DARK = (0.7, 0.95); TAG_WHITE = (0.06, 0.25)   # black 「ルール」 tag: dark 0.84, white text 0.13 on every sample
DESC_YS = (685, 755); DESC_MIN = 0.45               # black one-line description tag (dark 0.62) at y 685-730; in an イベントマッチ
                                                    # a pink event-name tag (「ツキイチ・イベントマッチ」) takes that place and
                                                    # pushes it 70 px down (dark 0.15 at 685, 0.5+ at 755)
ID_CONTRAST = 100; IDS_MIN = 6                      # '#nnnn' of a card: 2-98 percentile spread of its grey levels; cards that have it


def rule_tag(f):
    """(dark share, white share) of the 「ルール」 tag box"""
    box = f[285:335, 830:1090]                     # white = every channel > 200 (cv2: ~20x faster than box.min(axis=2) > 200)
    return dark_share(box, 40), cv2.countNonZero(cv2.inRange(box, (201, 201, 201), (255, 255, 255))) / (box.shape[0] * box.shape[1])


def rule_desc(f):
    """dark share of the description tag at each of DESC_YS"""
    return [dark_share(f[y:y + 45, 700:1210], 40) for y in DESC_YS]


def rule_ids(f):
    """contrast of the '#nnnn' at the bottom-left of each card (white on dark cards, dark brown on bright ones), ally then enemy"""
    tops = card_tops(f)
    g = np.stack([cv2.cvtColor(f[t + 118:t + 142, x0 + 12:x0 + 75], cv2.COLOR_BGR2GRAY).ravel() for x0 in CARD_X.values() for t in tops])
    lo, hi = np.percentile(g, (2, 98), axis=1)     # all 8 in one call: the same values as one np.percentile per crop, 1/16 of the time
    return [float(v) for v in hi - lo]


def looks_like_rule(f):
    """any rule: only the layout is checked, never the rule name. The cheap checks first (every sample of every state)"""
    d, w = rule_tag(f)
    if not (TAG_DARK[0] < d < TAG_DARK[1] and TAG_WHITE[0] < w < TAG_WHITE[1]): return False
    if max(rule_desc(f)) < DESC_MIN: return False
    return sum(c >= ID_CONTRAST for c in rule_ids(f)) >= IDS_MIN


def rule_checks(f):
    """all three checks of looks_like_rule without stopping at the first that fails, for the diagnostics of a missed rule
    screen (recorder.MissWatch): -> dict(tag, desc, ids: passed or not, and the measured values). ~0.3 ms"""
    d, w = rule_tag(f); desc = rule_desc(f); ids = rule_ids(f)
    return dict(tag=bool(TAG_DARK[0] < d < TAG_DARK[1] and TAG_WHITE[0] < w < TAG_WHITE[1]), desc=bool(max(desc) >= DESC_MIN),
                ids=sum(c >= ID_CONTRAST for c in ids) >= IDS_MIN, tag_dark=d, tag_white=w, desc_dark=desc, id_contrast=ids)


def main():
    src, out = sys.argv[1], sys.argv[2]; os.makedirs(out, exist_ok=True)
    cap = cv2.VideoCapture(src); fps = cap.get(cv2.CAP_PROP_FPS); step = int(round(fps / 2)); i = 0; t0 = time.time()
    state = None; run = []
    def flush():
        if run:
            mid = run[len(run) // 2]; tag = f'{state}_{run[0][0]:07.1f}-{run[-1][0]:07.1f}'
            cv2.imwrite(os.path.join(out, tag + '.png'), mid[1]); print(tag, flush=True)
    while True:
        if i % step:
            if not cap.grab(): break
            i += 1; continue
        ok, f = cap.read()
        if not ok: break
        t = i / fps
        s = 'rule' if looks_like_rule(f) else 'result' if looks_like_result(f) else None
        if s != state:
            flush(); state = s; run = []
        if s: run.append((t, f))
        i += 1
    flush(); print('done', round(time.time() - t0), 's')

if __name__ == '__main__':
    main()
