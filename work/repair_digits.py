"""Repair stored rows whose small 8 was read as 6 / 0 (before result_parser.HOLES, 2026-10-29).

The stored result screen (matches.result_image) and own panel (matches.medal_image) are read again with today's glyphs.
A stored value is changed only when the new reading differs from it exactly by 8s in place of 6s / 0s and the row's
points are the same (the same row); anything else is reported and left alone. Changed: match_players, the rows of
matches.raw_json, the players of the match's JSON beside the images, and a line in matches.notes.

    python work/repair_digits.py [DB]            # dry run: print what would change
    python work/repair_digits.py [DB] --apply    # backend stopped; copies the DB to DB.bak-repair-digits first
"""
import cv2, json, os, sqlite3, sys
sys.path.insert(0, os.path.dirname(__file__))
from result_parser import Glyphs, row_glyphs, STATS, STAT_X
from weapon_match import RESULT_ROWS
import panel

ROOT = os.path.join(os.path.dirname(__file__), '..')
FIELDS = ('kills_assists', 'deaths', 'specials')
NOTE = '2026-10-29 repair: small 8 had been read as 6 / 0'


def only_8s(old, new):
    """new is old with some 6 / 0 digits read as 8 (both 2-digit strings)"""
    return old != new and len(old) == len(new) and all(a == b or (b == '8' and a in '60') for a, b in zip(old, new))


def read_rows(f, g):
    """[(points, kills, deaths, specials)] of the 8 scoreboard rows, as strings ('' when unread)"""
    out = []
    for y in RESULT_ROWS.values():
        pm, pb, sm, sb = row_glyphs(f, y)
        groups = ['', '', '']
        for b, ch in zip(sb, g.read(sm, sb, 'small')[0]):
            for gi, (x0, x1) in enumerate(STAT_X):
                if x0 <= STATS[2] + b[0] <= x1: groups[gi] += ch
        out.append((g.read(pm, pb, 'big')[0].rstrip('p'), *(s.lstrip('x') for s in groups)))
    return out


def read_panel_row(f, g):
    text = [g.read(m, b, w)[0] for (m, b), w in zip(panel.parts(f), ('panel_big',) + ('panel_small',) * 3)]
    return (text[0].rstrip('p'), *text[1:])


def path(p):
    return os.path.join(ROOT, p.replace('\\', '/'))


def plan(db):
    """-> (changes, problems): changes = [(match_id, player rowid, field, old, new, where)]"""
    c = sqlite3.connect(db); g = Glyphs(); changes = []; problems = []
    for mid, rimg, mimg, raw in c.execute('select id, result_image, medal_image, raw_json from matches').fetchall():
        players = c.execute('select rowid, team, is_self, result_row, points, ' + ', '.join(FIELDS) + ' from match_players where match_id = ?', (mid,)).fetchall()
        if rimg and os.path.exists(path(rimg)) and raw:
            rows = json.loads(raw)['rows']; read = read_rows(cv2.imread(path(rimg)), g)
            for rowid, team, is_self, rr, pts, *vals in players:
                if rr is None: continue
                ri = [i for i, r in enumerate(rows) if r.get('hteam') == team][rr]
                new = read[ri]
                if new[0] != str(pts): problems.append((mid, rows[ri]['row'], f'points {pts} read as {new[0]}')); continue
                for k, old, nv in zip(FIELDS, vals, new[1:]):
                    ov = '%02d' % old if old is not None else ''
                    if ov == nv: continue
                    if only_8s(ov, nv): changes.append((mid, rowid, k, old, int(nv), rows[ri]['row']))
                    else: problems.append((mid, rows[ri]['row'], f'{k} {ov} read as {nv}'))
        elif mimg and os.path.exists(path(mimg)):
            new = read_panel_row(cv2.imread(path(mimg)), g)
            for rowid, team, is_self, rr, pts, *vals in players:
                if not is_self or rr is not None: continue
                if new[0] != str(pts): problems.append((mid, 'panel', f'points {pts} read as {new[0]}')); continue
                for k, old, nv in zip(FIELDS, vals, new[1:]):
                    ov = '%02d' % old if old is not None else ''
                    if ov != nv and only_8s(ov, nv): changes.append((mid, rowid, k, old, int(nv), 'panel'))
                    elif ov != nv: problems.append((mid, 'panel', f'{k} {ov} read as {nv}'))
    c.close()
    return changes, problems


def apply(db, changes):
    c = sqlite3.connect(db)
    with sqlite3.connect(db + '.bak-repair-digits') as bak: c.backup(bak)    # not a file copy: pages still in the -wal count
    bak.close()
    raw_key = {'kills_assists': 'kills', 'deaths': 'deaths', 'specials': 'specials'}
    with c:
        for mid in sorted({ch[0] for ch in changes}):
            mine = [ch for ch in changes if ch[0] == mid]
            for _, rowid, k, old, new, row in mine:
                c.execute(f'update match_players set {k} = ? where rowid = ?', (new, rowid))
            raw, notes, rimg = c.execute('select raw_json, notes, result_image from matches where id = ?', (mid,)).fetchone()
            if raw:
                d = json.loads(raw)
                for _, _, k, _, new, row in mine:
                    for r in d['rows']:
                        if r['row'] == row: r[raw_key[k]] = '%02d' % new
                c.execute('update matches set raw_json = ? where id = ?', (json.dumps(d, ensure_ascii=False), mid))
            c.execute('update matches set notes = ? where id = ?', ('; '.join(x for x in (notes, NOTE) if x), mid))
            js = rimg and path(rimg).replace('_result.png', '.json')
            if js and os.path.exists(js):                      # the record as inserted, kept beside the images
                rec = json.load(open(js, encoding='utf-8'))
                slots = dict(c.execute('select rowid, slot from match_players where match_id = ?', (mid,)).fetchall())
                for _, rowid, k, _, new, _ in mine:
                    for p in rec['players']:
                        if p['slot'] == slots[rowid]: p[k] = new
                json.dump(rec, open(js, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    c.close()


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    db = args[0] if args else os.path.join(ROOT, 'data', 'splatoon.db')
    changes, problems = plan(db)
    for ch in changes: print('  match {} {:6s} {:13s} {} -> {}'.format(ch[0], ch[5], ch[2], ch[3], ch[4]))
    for p in problems: print('  LEFT ALONE match {} {}: {}'.format(*p))
    print(f'{len(changes)} values in {len({ch[1] for ch in changes})} rows of {len({ch[0] for ch in changes})} matches; {len(problems)} left alone')
    if '--apply' in sys.argv: apply(db, changes); print('applied (backup: ' + db + '.bak-repair-digits)')
