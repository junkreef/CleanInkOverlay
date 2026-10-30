"""Watch the OBS Virtual Camera; when the result screen appears, parse it once and log the result.

    python work/live_result_watch.py --minutes 30 --out samples/live_results
"""
import argparse, json, os, sys, time
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from result_parser import parse, Glyphs, RESULT_ROWS, dark_share
from weapon_match import load_main_weapons
from live_capture import find_device


def looks_like_result(f):
    """dark result panel with 8 dark player rows and a bright header bar. The small row boxes are checked first: any
    frame of a match fails there, before the whole panel (1 ms) is looked at"""
    if any(dark_share(f[y - 15:y + 55, 1040:1130], 40) <= 0.3 for y in RESULT_ROWS.values()):
        return False
    if dark_share(f[300:1000, 800:1850], 40) < 0.3:
        return False
    return (f[235:285, 925:1710].max(axis=2) > 120).mean() > 0.3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--device', type=int, default=None); ap.add_argument('--minutes', type=float, default=30)
    ap.add_argument('--out', default='samples/live_results'); a = ap.parse_args()
    idx = a.device if a.device is not None else find_device()[0]
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW); cap.set(3, 1920); cap.set(4, 1080)
    icons = load_main_weapons(); glyphs = Glyphs(); os.makedirs(a.out, exist_ok=True)
    print('watching device', idx, flush=True)
    t_end = time.time() + a.minutes * 60; stable = 0; parsed = False; last_status = time.time(); n = 0
    while time.time() < t_end:
        ok, f = cap.read()
        if not ok: time.sleep(0.05); continue
        n += 1
        if n % 6: continue  # ~10 checks per second
        if looks_like_result(f):
            stable += 1
            if stable == 10 and not parsed:  # ~1 s of stable result screen
                r = parse(f, icons, glyphs); parsed = True
                ts = time.strftime('%Y-%m-%d_%H-%M-%S'); cv2.imwrite(os.path.join(a.out, ts + '.png'), f)
                json.dump(r, open(os.path.join(a.out, ts + '.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                print(f'[{ts}] RESULT self={r["self_result"]} paint {r["pct_left"]} / {r["pct_right"]}', flush=True)
                for row in r['rows']:
                    print(f'   {row["row"]:5s} {"*" if row["self"] else " "} {row["weapon"]:22s} {row["points"]:>5s}p k{row["kills"]} d{row["deaths"]} s{row["specials"]}  (w={row["weapon_score"]:.2f} g={row["min_glyph_score"]})', flush=True)
        else:
            stable = 0; parsed = False
        if time.time() - last_status > 60:
            last_status = time.time(); print(f'... alive, {n} frames', flush=True)
    cap.release()


if __name__ == '__main__':
    main()
