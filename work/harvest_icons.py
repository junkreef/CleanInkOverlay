"""Bootstrap the captured weapon icon templates (weapon_icons.py) from the stored result screens.

    uv run python work/harvest_icons.py [--dry] [GLOB]     # default GLOB: samples/matches/*_result.png

Every result row is matched against the wiki icons (plus the old hand-cut crops in assets/real_icons/result_screen, which
override a missing or bad wiki icon, as the matcher did before); rows that pass weapon_icons.harvestable become samples,
best score first, up to MAX_SAMPLES per weapon spread over the row positions. Screens from H.264 recordings are skipped:
their panel is not flat, so the alpha would be noise. The old hand-cut crops are added last, for weapons still short of
samples (padded onto the panel colour).

Scope variants (SCOPE_PAIRS) are not taken from the match: the result screen draws the scope in dark grey a few levels above
the panel, so the matcher (wiki icons or templates) confuses them (the old matcher had リッター4K / 4Kスコープ the wrong way
round on 34 of 52 rows). Their rows are first labelled by the mean brightness inside the wiki 4Kスコープ / スプラスコープ shape
minus the non-scope shape (4K: <= 9.1 vs >= 14.6 on rows 2-4), then, once the templates exist, every sample of a pair is
checked again with weapon_match.shape_decision and moved when the shape disagrees: the brightness depends on the row
(リッター4K on a lose1 row read 14.7). The shape answers on all 89 stored rows were confirmed by the user on 2026-10-15.
The recorder keeps collecting from live result screens afterwards; this script is only for the screens already on disk.
"""
import argparse, collections, glob, os, sys
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from weapon_icons import IconLibrary, harvestable, lossless, imread_u, panel_bg, icon_window
from weapon_match import load_wiki_icons, match, shape_decision, RESULT_ROWS, ROOT
from result_parser import WEAPON, crop as rcrop

REAL_DIR = os.path.join(ROOT, 'assets', 'real_icons', 'result_screen')
SCOPE_PAIRS = [('リッター4K', '4Kスコープ', 12), ('リッター4Kカスタム', '4Kスコープカスタム', 10.5), ('スプラチャージャー', 'スプラスコープ', 20),
               ('スプラチャージャーコラボ', 'スプラスコープコラボ', 60), ('スプラチャージャーFRST', 'スプラスコープFRST', 25)]   # (no scope, scope, level split)


def scope_level(row_crop, wiki, plain, scoped):
    """mean max-channel level of the crop inside the scope part (scoped wiki shape minus the plain one, eroded 1 px)"""
    m = cv2.erode(((wiki[scoped][..., 3] > 128) & ~(wiki[plain][..., 3] > 128)).astype(np.uint8), np.ones((2, 2), np.uint8)) > 0
    y, x = icon_window(row_crop, wiki[scoped])
    return float(row_crop[y:y + m.shape[0], x:x + m.shape[1]].max(axis=2)[m].mean())


def scope_label(row_crop, ranked, wiki):
    """the scope pair's answer for a row whose two best wiki matches include one of the pair, else None"""
    for score, name, *_ in ranked[:2]:
        for plain, scoped, split in SCOPE_PAIRS:
            if name in (plain, scoped) and score >= 0.85 and plain in wiki and scoped in wiki:
                return scoped if scope_level(row_crop, wiki, plain, scoped) >= split else plain, score
    return None


def padded(patch, shape=(WEAPON[1] - WEAPON[0], WEAPON[3] - WEAPON[2])):
    """a tight hand-cut icon crop placed in the middle of a row-sized canvas of its panel colour"""
    out = np.empty(shape + (3,), np.uint8); out[:] = panel_bg(patch)
    y, x = (shape[0] - patch.shape[0]) // 2, (shape[1] - patch.shape[1]) // 2
    out[y:y + patch.shape[0], x:x + patch.shape[1]] = patch
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pattern', nargs='?', default=os.path.join(ROOT, 'samples', 'matches', '*_result.png'))
    ap.add_argument('--dry', action='store_true', help='report only, write nothing')
    a = ap.parse_args()
    wiki = load_wiki_icons()
    real = {f[:-4]: imread_u(os.path.join(REAL_DIR, f), cv2.IMREAD_COLOR) for f in os.listdir(REAL_DIR) if f.endswith('.png')} if os.path.isdir(REAL_DIR) else {}
    icons = dict(wiki); icons.update(real)              # the matcher's icon set before the captured templates existed
    cands = collections.defaultdict(list); skipped = 0; n_rows = 0; n_scope = 0; pos = collections.Counter()
    files = sorted(glob.glob(a.pattern))
    for i, p in enumerate(files):
        f = imread_u(p, cv2.IMREAD_COLOR)
        if f is None: continue
        stem = os.path.basename(p)[:-len('_result.png')]
        for label, y in RESULT_ROWS.items():
            c = rcrop(f, WEAPON, y); n_rows += 1
            if not lossless(c): skipped += 1; continue
            ranked = match(c, icons); best = ranked[0]
            scope = scope_label(c, ranked, wiki)
            if scope:
                cands[scope[0]].append((scope[1], f'{stem}_{label}', c)); n_scope += 1
            elif harvestable(dict(weapon=best[1], weapon_score=best[0], weapon_conf=best[3])):
                cands[best[1]].append((best[0], f'{stem}_{label}', c))
                if best[1] in wiki: pos[icon_window(c, wiki[best[1]])] += 1
        if (i + 1) % 20 == 0: print(f'{i + 1}/{len(files)} screens', flush=True)
    lib = IconLibrary(); added = collections.Counter()
    for name, items in sorted(cands.items()):
        # the wiki icon aligns and trims every weapon it has (リッター4K's was thought bad, but that was the 4K labels
        # being the wrong way round: aligning it differently put its template 6 px off 4Kスコープ's)
        for score, stem, c in sorted(items, key=lambda t: -t[0]):  # best first; add_sample keeps the row positions spread
            if lib.add_sample(name, c, stem, wiki=wiki.get(name)): added[name] += 1
    for name, patch in real.items():
        if patch is not None and lib.add_sample(name, padded(patch), 'real_icons'): added[name] += 1
    for plain, scoped, _ in SCOPE_PAIRS:                           # second pass: the shape has the last word
        if plain not in lib.templates or scoped not in lib.templates: continue
        for name in (plain, scoped):
            for stem in list(lib.sample_stems(name)):
                other = scoped if name == plain else plain
                if shape_decision(lib.sample(name, stem), lib.templates, plain, scoped)[0] == other:
                    print(f'shape relabels {stem}: {name} -> {other}')
                    lib.drop_sample(name, stem, to=other, wiki=wiki.get(name), wiki_to=wiki.get(other))
    print(f'rows {n_rows}, skipped (not lossless) {skipped}, scope-pair rows labelled by level {n_scope}, weapons with samples {len(cands)}, templates {len(lib.templates)}')
    print('icon window (y, x) in the row crop, most common:', pos.most_common(6))
    few = sorted((n, k) for k, n in added.items() if n < 3)
    print(f'weapons with < 3 samples ({len(few)}):', ', '.join(f'{k}({n})' for n, k in few))
    if a.dry: print('--dry: nothing written')
    else: lib.save(); print('written:', os.path.relpath(lib.captured_dir, ROOT), os.path.relpath(lib.samples_dir, ROOT))


if __name__ == '__main__':
    main()
