"""Read the repo's test screens with a release package's own recorder, to see that every template, glyph set, signature
and weapon icon loads from where the package sits (tools/smoke_release.py puts it under a folder with a Japanese name:
cv2.imread, for one, cannot open such a path). It is run by the package's Python, not by the developer's:

    <package>\\runtime\\python\\python.exe -X utf8 tools\\smoke_frames.py work\\frames

Prints one JSON line: how many screens each check recognised, and what the scoreboard of 0268_result_scoreboard.png read.
"""
import glob, json, os, sys
import cv2
from app.store import Store                                   # the package's app/ (its ._pth); puts its work/ on sys.path
import recorder as R
from result_parser import parse
from weapon_icons import imread_u

EXPECTED_SCREENS = ('rule', 'result', 'medals', 'judge', 'map', 'hud')
SCOREBOARD = ('0268_result_scoreboard.png', 'コンブトラック')


def main(frames):
    store = Store(); rec = R.Recorder('smoke', store, dry=True, log=lambda *a: None)
    assert os.path.normcase(os.path.abspath(R.__file__)).startswith(os.path.normcase(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))))), R.__file__
    seen = {}
    for p in sorted(glob.glob(os.path.join(frames, '*.png'))):
        f = imread_u(p, cv2.IMREAD_COLOR)
        if f is None or f.shape[:2] != (1080, 1920): continue
        for screen, check in R.CHECK.items():
            if check(f): seen[screen] = seen.get(screen, 0) + 1
    missing = [s for s in EXPECTED_SCREENS if s not in seen]
    assert not missing, f'no test screen was recognised as {missing}: {seen}'
    res = parse(imread_u(os.path.join(frames, SCOREBOARD[0]), cv2.IMREAD_COLOR), rec.icons, rec.glyphs, store.signatures(), add_unknown=False)
    weapons = [r.get('weapon') for r in res['rows']]
    assert res.get('stage') == SCOREBOARD[1] and len(weapons) == 8 and all(weapons), res
    print(json.dumps({'screens': seen, 'templates': len(rec.icons), 'stage': res['stage'], 'weapons': weapons}, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1])
