"""Make the weapon icon groups to confirm for the result screens already stored.

    uv run python work/confirm_backfill.py [--dry]

A row that only a wiki icon names, with too little confidence to become a sample (UNKNOWN_BELOW <= score <
HARVEST_MIN_SCORE, e.g. ホットブラスター艶 0.926), waits in an unknown group with the wiki's name as its guess, to be
confirmed on the signatures page (the recorder does this for live screens: Recorder.harvest_icons). This covers the
screens stored before that. The rows are linked in raw_json, so the page shows the screens and naming fills the matches.
Restart a running backend afterwards: it keeps its own copy of the icon library.
"""
import argparse, glob, os, sys
import cv2
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for p in (ROOT, os.path.dirname(__file__)):
    if p not in sys.path: sys.path.insert(0, p)
from app.store import Store, rel
from weapon_icons import imread_u, lossless, group_name, HARVEST_MIN_SCORE
from weapon_match import load_main_weapons, match, fit_group, RESULT_ROWS, UNKNOWN_BELOW
from result_parser import WEAPON, crop as rcrop


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry', action='store_true', help='report only, write nothing')
    a = ap.parse_args()
    store = Store(); lib = store.weapon_icons()
    icons = load_main_weapons(captured_dir=lib.captured_dir)
    grouped = {s for gid in lib.groups() for s in lib.sample_stems(group_name(gid))}
    found = []
    for p in sorted(glob.glob(os.path.join(store.images_dir, '*_result.png'))):
        if '.mp4' in p: continue                                   # recordings: H.264, see Recorder.harvest_icons
        f = imread_u(p, cv2.IMREAD_COLOR); ts = os.path.basename(p)[:-len('_result.png')]
        for row, y in RESULT_ROWS.items():
            score, name, stage, _ = match(c := rcrop(f, WEAPON, y), icons)[0]
            if name in icons.captured or stage == 'variant' or not UNKNOWN_BELOW <= score < HARVEST_MIN_SCORE: continue
            if f'{ts}_{row}' in grouped or not lossless(c): continue
            found.append((name, score, ts, row))
            if a.dry: continue
            gid = fit_group(c, lib)
            if gid: lib.add_sample(group_name(gid), c, f'{ts}_{row}')
            else: gid = lib.new_group(c, f'{ts}_{row}', guess=name)
            store.link_weapon_unknown(rel(p), row, gid)
    for name, score, ts, row in found: print(f'{name:24s} {score:.3f}  {ts} {row}')
    if a.dry: print(f'--dry: {len(found)} rows, nothing written')
    else:
        store.save_libraries()
        print(f'{len(found)} rows in {len(lib.groups())} groups to confirm; restart a running backend to see them')
    store.close()


if __name__ == '__main__':
    main()
