"""Merge the names other people gave signatures into assets/signatures.json, so the next release ships them.

A release keeps the user's own labelling in %LOCALAPPDATA%\\CleanInkOverlay\\assets\\signatures.json (app.paths). That file
is not a full library: it holds only what the user added on top of the library their release shipped (new ids, ids
they named differently), so it must be merged, never copied over ours. Each labelled entry of an incoming file is:

    added       a new id whose text matches nothing we have (the same text seen by someone else usually gets its own
                id, since the id is a hash of the pixels; a second signature of a text is harmless)
    named       an id we have without a label
    known       the same id with the same label, or a new id that already reads as one of ours with the same label
                ("reads as" = what the recorder would answer: the threshold it identifies that kind with)
    CONFLICT    the same id with another label, or a new id that reads as one of ours with another label: not merged,
                look at both and decide (Web UI, or edit the file)
    skipped     a signature of another size than ours of that kind (cut by an older version)

Unlabelled entries are ignored (nothing to learn from them), and so are kinds the library drops (signatures.DROPPED_KINDS).

    python work/merge_signatures.py their_signatures.json [more.json ...]            # dry run: prints what would change
    python work/merge_signatures.py their_signatures.json [more.json ...] --apply    # writes assets/signatures.json

Run it with the backend stopped. An id this merge names is not filled into the DB of this checkout (matches stored under
it stay unnamed here); the Web UI's labelling does that, a release's users get it on their next start (Library.adopted).
"""
import argparse, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from signatures import LIB, MATCH_THR, load_items
from medals import MEDAL_THR
from result_parser import BANNER_THR, MODE_THR
from panel import WEAPON_THR
from recorder import TITLE_THR

# "reads as" = what the recorder would answer for this signature: the threshold each kind is identified with
THRESHOLDS = {'medal': MEDAL_THR, 'stage': BANNER_THR, 'rule': BANNER_THR, 'mode': MODE_THR, 'panel_weapon': WEAPON_THR,
              'title': TITLE_THR}


def best_match(sig, kind, items):
    """(id, correlation) of the item of this kind (and signature size) that reads most like sig; (None, -1) if none"""
    best = (None, -1.0)
    for k, it in items.items():
        if it['kind'] != kind or len(it['sig']) != len(sig): continue
        c = float(np.corrcoef(sig, np.array(it['sig'], np.float32))[0, 1])
        if c > best[1]: best = (k, c)
    return best


def merge(items, incoming, thresholds=THRESHOLDS):
    """merge the labelled entries of `incoming` (id -> {kind, label, sig}) into `items` in place; returns the report:
    a list of (outcome, id, kind, label, detail) with outcome one of added / named / known / conflict / skipped.
    thresholds: kind -> the correlation from which a signature reads as one of ours (signatures.MATCH_THR otherwise)"""
    report = []
    for k, it in incoming.items():
        kind, label = it.get('kind'), it.get('label')
        if not label or not it.get('sig'): continue
        if k in items:
            have = items[k].get('label')
            if not have: items[k]['label'] = label; report.append(('named', k, kind, label, ''))
            elif have == label: report.append(('known', k, kind, label, ''))
            else: report.append(('conflict', k, kind, label, f'ours is {have!r}'))
            continue
        sizes = {len(o['sig']) for o in items.values() if o['kind'] == kind}
        if sizes and len(it['sig']) not in sizes:
            report.append(('skipped', k, kind, label, f'{len(it["sig"])} values, ours have {sorted(sizes)}')); continue
        sig = np.array(it['sig'], np.float32)
        mk, c = best_match(sig, kind, items)
        if mk is not None and c >= thresholds.get(kind, MATCH_THR):
            have = items[mk].get('label')
            if have == label: report.append(('known', k, kind, label, f'reads as {mk} ({c:.2f})')); continue
            if have:
                report.append(('conflict', k, kind, label, f'reads as {mk} {have!r} ({c:.2f})')); continue
            # reads as one of ours that has no name yet: name ours too, and keep theirs as a second signature
            items[mk]['label'] = label; report.append(('named', mk, kind, label, f'from {k} ({c:.2f})'))
        items[k] = {'kind': kind, 'label': label, 'sig': it['sig']}
        report.append(('added', k, kind, label, f'closest {mk} ({c:.2f})' if mk else ''))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('files', nargs='+', help="other people's signatures.json")
    ap.add_argument('--library', default=LIB, help='the library to merge into (default: assets/signatures.json)')
    ap.add_argument('--apply', action='store_true', help='write the library (default: dry run)')
    a = ap.parse_args(argv)
    items = load_items(a.library); before = len(items); changed = False
    for path in a.files:
        report = merge(items, load_items(path))
        print(f'{path}:')
        if not report: print('  no labelled entries')
        for outcome, k, kind, label, detail in sorted(report, key=lambda r: ('conflict', 'skipped', 'named', 'added', 'known').index(r[0])):
            if outcome == 'known': continue
            print(f'  {outcome.upper() if outcome == "conflict" else outcome:8} {k} {kind} {label!r}' + (f'  ({detail})' if detail else ''))
        if known := sum(r[0] == 'known' for r in report): print(f'  known    {known} entr{"y" if known == 1 else "ies"} we already have')
        changed |= any(r[0] in ('added', 'named') for r in report)
    print(f'library: {before} -> {len(items)} signatures')
    if not changed: print('nothing to write'); return 0
    if not a.apply: print('dry run: nothing written (--apply to write)'); return 0
    with open(a.library, 'w', encoding='utf-8') as fh: json.dump(items, fh, ensure_ascii=False)
    print('written:', a.library)
    return 0


if __name__ == '__main__':
    sys.exit(main())
