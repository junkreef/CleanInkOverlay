"""Per-frame features for special detection: gauge ring (top right) + 8 HUD slots, 10 fps -> CSV.
    python work/probe_sp.py VIDEO OUT.csv
"""
import cv2, numpy as np, sys, os, time
sys.path.insert(0, os.path.dirname(__file__))
import hud
GAUGE = (40, 200, 1690, 1870)

def ring_mask():
    h, w = GAUGE[1] - GAUGE[0], GAUGE[3] - GAUGE[2]
    yy, xx = np.mgrid[:h, :w]; cy, cx = 80, 90
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    return (r > 62) & (r < 84)
RING = ring_mask()

def gauge_feats(f):
    g = hud.crop(f, GAUGE); hsv = cv2.cvtColor(g, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[..., 0][RING], hsv[..., 1][RING], hsv[..., 2][RING]
    orange = ((H >= 5) & (H <= 30) & (S > 120) & (V > 150)).mean()
    white = ((S < 60) & (V > 200)).mean()
    dark = (V < 70).mean()
    return orange, white, dark

def slot_feats(f, i):
    im = hud.slot_img(f, i); hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV); S = hsv[..., 1]; V = hsv[..., 2]; low = S < 50
    return (float((low & (V < 120)).mean()), float((low & (V >= 205)).mean()), float(V.mean()), float(S.mean()), float(((S > 100) & (V > 180)).mean()))

def main():
    src, out = sys.argv[1], sys.argv[2]
    cap = cv2.VideoCapture(src); fps = cap.get(cv2.CAP_PROP_FPS); step = max(1, int(round(fps / 10))); i = 0; t0 = time.time()
    with open(out, 'w') as fo:
        fo.write('t,vis,g_or,g_wh,g_dk,' + ','.join(f's{s}_{k}' for s in range(8) for k in ('dark', 'white', 'v', 's', 'bright')) + '\n')
        while True:
            if i % step:
                if not cap.grab(): break
                i += 1; continue
            ok, f = cap.read()
            if not ok: break
            t = i / fps; vis = hud.hud_visible(f)
            row = [t, int(vis)] + list(gauge_feats(f)) + [x for s in range(8) for x in slot_feats(f, s)]
            fo.write(','.join(f'{x:.3f}' if isinstance(x, float) else str(x) for x in row) + '\n')
            i += 1
    print('done', i, 'frames', round(time.time() - t0), 's')

if __name__ == '__main__':
    main()
