"""Pass 1: scan the video at a fixed sample rate and dump cheap per-frame features to CSV."""
import cv2, numpy as np, csv, sys, time

SRC = sys.argv[1] if len(sys.argv) > 1 else '../2026-09-12_14-13-43.mp4'
OUT = sys.argv[2] if len(sys.argv) > 2 else 'features.csv'
STEP = 10  # every 10th frame => 6 fps at 60fps source

# HUD squid slots (x0,x1), y range shared. Left 4 = my team, right 4 = enemy team.
SLOT_X = [(527, 597), (622, 692), (711, 781), (799, 869), (1057, 1127), (1145, 1215), (1233, 1303), (1320, 1390)]
SLOT_Y = (38, 112)
TIMER = (48, 104, 910, 1010)          # y0,y1,x0,x1 black box with white digits
KILLFEED = (995, 1045, 720, 1200)     # bottom center black band
DEATH_BUBBLE = (330, 470, 780, 1140)  # center black splat with white text
POINTS = (45, 110, 1500, 1690)

def sat_frac(bgr, smin=110, vmin=110):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return float(((hsv[...,1] > smin) & (hsv[...,2] > vmin)).mean())

def dark_frac(bgr, vmax=60):
    return float((bgr.max(axis=2) < vmax).mean())

def white_frac(bgr, vmin=200):
    return float((bgr.min(axis=2) > vmin).mean())

def crop(f, r):
    return f[r[0]:r[1], r[2]:r[3]]

cap = cv2.VideoCapture(SRC)
fps = cap.get(cv2.CAP_PROP_FPS)
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
t0 = time.time()
with open(OUT, 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['frame', 't'] + [f'slot{i}_sat' for i in range(8)] + [f'slot{i}_dark' for i in range(8)]
               + ['timer_dark', 'timer_white', 'kf_dark', 'kf_white', 'db_dark', 'db_white', 'pts_white',
                  'mean_v', 'mean_s'])
    i = 0
    while True:
        if i % STEP:
            if not cap.grab(): break
            i += 1; continue
        ok, f = cap.read()
        if not ok: break
        row = [i, round(i / fps, 3)]
        slots = [f[SLOT_Y[0]:SLOT_Y[1], x0:x1] for x0, x1 in SLOT_X]
        row += [round(sat_frac(s), 3) for s in slots]
        row += [round(dark_frac(s, 90), 3) for s in slots]
        tm = crop(f, TIMER); kf = crop(f, KILLFEED); db = crop(f, DEATH_BUBBLE); pt = crop(f, POINTS)
        row += [round(dark_frac(tm), 3), round(white_frac(tm), 3), round(dark_frac(kf), 3), round(white_frac(kf), 3),
                round(dark_frac(db), 3), round(white_frac(db), 3), round(white_frac(pt), 3)]
        hsv = cv2.cvtColor(cv2.resize(f, (192, 108)), cv2.COLOR_BGR2HSV)
        row += [round(float(hsv[...,2].mean()), 1), round(float(hsv[...,1].mean()), 1)]
        w.writerow(row)
        i += 1
        if i % 6000 == 0:
            print(f'{i}/{n} frames, {time.time()-t0:.0f}s', flush=True)
print('done', i, 'frames in', round(time.time() - t0), 's')
