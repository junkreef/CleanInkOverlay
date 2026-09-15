"""Pass 1 (v2): richer per-frame features at 10 fps -> CSV."""
import cv2, numpy as np, csv, sys, time
SRC, OUT = sys.argv[1], sys.argv[2]
STEP = 6  # 60fps/6 = 10 fps
SLOT_X = [(527, 597), (622, 692), (711, 781), (799, 869), (1057, 1127), (1145, 1215), (1233, 1303), (1320, 1390)]
SLOT_Y = (38, 112)
TIMER = (48, 104, 910, 1010); POINTS = (45, 110, 1500, 1690)
KILLFEED = (995, 1045, 720, 1200); BUBBLE = (390, 490, 780, 1140); BOTTOM = (975, 1065, 780, 1140); RESPAWN = (960, 1030, 1550, 1910)
TPL_YAR = cv2.imread('templates/yarareta.png', 0); TPL_RSP = cv2.imread('templates/respawn.png', 0)
def crop(f, r): return f[r[0]:r[1], r[2]:r[3]]
def white_mask(bgr): return (bgr.min(axis=2) > 190).astype(np.uint8) * 255
def tm(bgr, tpl): return float(cv2.matchTemplate(white_mask(bgr), tpl, cv2.TM_CCOEFF_NORMED).max())
def slot_feats(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV); S = hsv[..., 1]; V = hsv[..., 2]; low = S < 50
    satm = (S > 110) & (V > 110)
    hue = float(np.median(hsv[..., 0][satm])) if satm.sum() > 20 else -1
    return [satm.mean(), (low & (V < 120)).mean(), (low & (V >= 205)).mean(), hue]
cap = cv2.VideoCapture(SRC); fps = cap.get(cv2.CAP_PROP_FPS); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); t0 = time.time()
with open(OUT, 'w', newline='') as fh:
    w = csv.writer(fh)
    hdr = ['frame', 't']
    for i in range(8): hdr += [f's{i}_sat', f's{i}_dark', f's{i}_white', f's{i}_hue']
    hdr += ['timer_dark', 'timer_bright', 'pts_white', 'kf_dark', 'kf_white', 'bub_dark', 'bub_yar', 'bot_yar', 'rsp', 'mean_v']
    w.writerow(hdr)
    i = 0
    while True:
        if i % STEP:
            if not cap.grab(): break
            i += 1; continue
        ok, f = cap.read()
        if not ok: break
        row = [i, round(i / fps, 3)]
        for x0, x1 in SLOT_X: row += [round(v, 3) for v in slot_feats(f[SLOT_Y[0]:SLOT_Y[1], x0:x1])]
        tmr = crop(f, TIMER); tv = cv2.cvtColor(tmr, cv2.COLOR_BGR2HSV)[..., 2]
        row += [round(float((tv < 60).mean()), 3), round(float((tv > 170).mean()), 3)]
        row += [round(float((crop(f, POINTS).min(axis=2) > 200).mean()), 3)]
        kf = crop(f, KILLFEED); row += [round(float((kf.max(axis=2) < 60).mean()), 3), round(float((kf.min(axis=2) > 200).mean()), 3)]
        bub = crop(f, BUBBLE); row += [round(float((bub.max(axis=2) < 60).mean()), 3), round(tm(bub, TPL_YAR), 3)]
        row += [round(tm(crop(f, BOTTOM), TPL_YAR), 3), round(tm(crop(f, RESPAWN), TPL_RSP), 3)]
        row += [round(float(cv2.cvtColor(cv2.resize(f, (192, 108)), cv2.COLOR_BGR2HSV)[..., 2].mean()), 1)]
        w.writerow(row); i += 1
print('done', i, 'frames', round(time.time() - t0), 's', flush=True)
