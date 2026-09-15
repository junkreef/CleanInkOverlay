"""Scan a video at 2 fps for rule screens (8 player cards) and result screens; save one frame per run.
    python work/scan_screens.py VIDEO OUTDIR
"""
import cv2, numpy as np, sys, os, time
sys.path.insert(0, os.path.dirname(__file__))
from live_result_watch import looks_like_result

CARD_TOPS = [285, 435, 585, 735]; CARD_X = {'ally': 10, 'enemy': 1450}

def looks_like_rule(f):
    box = f[285:335, 830:1090]            # black 「ルール」 tag: dark 0.84, white text 0.13 on every sample
    sub = f[685:730, 700:1210]            # black one-line description tag: dark 0.62
    if not (0.7 < (box.max(axis=2) < 40).mean() < 0.95 and 0.06 < (box.min(axis=2) > 200).mean() < 0.25): return False
    if (sub.max(axis=2) < 40).mean() < 0.45: return False
    # cards carry a '#nnnn' at their bottom-left (white on dark cards, dark brown on bright ones): count contrasty ones
    ok = 0
    for x0 in CARD_X.values():
        for t in CARD_TOPS:
            g = cv2.cvtColor(f[t + 118:t + 142, x0 + 12:x0 + 75], cv2.COLOR_BGR2GRAY)
            ok += np.percentile(g, 98) - np.percentile(g, 2) >= 100
    return ok >= 6


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
