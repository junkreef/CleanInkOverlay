"""Check the captured weapon templates against the wiki icons on the stored result screens (leave-one-out).

    uv run python work/eval_icons.py [GLOB]     # default GLOB: samples/matches/*_result.png

For each result row: the answer of the old icon set (wiki + assets/real_icons) vs the answer of the captured templates,
where the templates built from this very screen are rebuilt without it (a weapon whose only sample is this row has no
template then, as on a screen of a weapon never seen before). Prints the agreement and the score margins.
"""
import collections, glob, os, sys
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from weapon_icons import IconLibrary, build_template, harvestable, lossless, imread_u
from weapon_match import load_wiki_icons, match, RESULT_ROWS, ROOT, UNKNOWN_BELOW
from result_parser import WEAPON, crop as rcrop
from harvest_icons import REAL_DIR


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'samples', 'matches', '*_result.png')
    wiki = load_wiki_icons()
    real = {f[:-4]: imread_u(os.path.join(REAL_DIR, f), cv2.IMREAD_COLOR) for f in os.listdir(REAL_DIR) if f.endswith('.png')} if os.path.isdir(REAL_DIR) else {}
    old = dict(wiki); old.update(real)
    lib = IconLibrary(); full = dict(lib.templates)
    by_stem = collections.defaultdict(list)             # screen stem -> weapons that have a sample from it
    for name in full:
        for s in lib.sample_stems(name): by_stem[s.rsplit('_', 1)[0]].append(name)
    tally = collections.Counter(); diffs = []; margins = []; unseen = []
    for p in sorted(glob.glob(pattern)):
        f = imread_u(p, cv2.IMREAD_COLOR)
        if f is None: continue
        stem = os.path.basename(p)[:-len('_result.png')]
        icons = dict(full)
        for name in set(by_stem.get(stem, [])):         # leave this screen's samples out
            d = os.path.join(lib.samples_dir, name)
            keep = [imread_u(os.path.join(d, x), cv2.IMREAD_COLOR) for x in sorted(os.listdir(d)) if not x.startswith(stem + '_')]
            t = build_template(keep, full[name], trim=wiki.get(name) if name not in real else None) if keep else None
            if t is None: icons.pop(name, None)
            else: icons[name] = t
        for label, y in RESULT_ROWS.items():
            c = rcrop(f, WEAPON, y)
            if not lossless(c): tally['skipped (H.264)'] += 1; continue
            o = match(c, old)[0]; n = match(c, icons)
            truth = o[1] if o[0] >= UNKNOWN_BELOW else None
            got = n[0][1] if n[0][0] >= UNKNOWN_BELOW else None
            conf = harvestable(dict(weapon=o[1], weapon_score=o[0], weapon_conf=o[3]))
            kind = 'confident' if conf else 'unsure'
            if got == truth: tally[f'{kind}: same'] += 1
            elif got is None: tally[f'{kind}: captured says unknown'] += 1; unseen.append((stem, label, truth, o[0], n[0][1], n[0][0], truth in icons))
            else: tally[f'{kind}: DIFFERENT'] += 1; diffs.append((stem, label, truth, o[0], o[3], got, n[0][0], n[0][3], n[1][1], n[1][0]))
            if got == truth and got is not None: margins.append((n[0][0], n[0][0] - n[1][0], n[0][2]))
    for k, v in sorted(tally.items()): print(f'{k:32s} {v}')
    if margins:
        s = np.array([m[0] for m in margins]); g = np.array([m[1] for m in margins])
        print(f'agreeing rows: top score min {s.min():.3f} p5 {np.percentile(s, 5):.3f} median {np.median(s):.3f}; '
              f'margin to runner-up min {g.min():.3f} p5 {np.percentile(g, 5):.3f}; decided by pair stage: {sum(m[2] == "pair" for m in margins)}')
    print('\nDIFFERENT (screen, row, old answer score conf -> captured answer score conf, runner-up):')
    for d in diffs: print('  ', d)
    print('\ncaptured says unknown (screen, row, old answer, old score, captured best, its score, template exists without this screen):')
    for u in unseen: print('  ', u)


if __name__ == '__main__':
    main()
