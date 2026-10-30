"""Regenerate assets/signatures.json from the stored screens, after a change to how banner / medal text is cut out.

Every stored result screen (stage / mode / rule) and 表彰 screen (medals) is read again with the current code. The new
signatures are labelled from what the DB already knows (the match's stage / mode / rule, the medal names), and the
DB's references are moved to the new ids: medals.sig_id (+ name while unlabelled) and the *_id keys in raw_json.
A banner that the DB has no name for stays unlabelled (nameable in the UI as before); a match whose column is empty
but whose signature is labelled elsewhere gets the label. Medals that the old code missed on a screen are added.

    python work/rebuild_signatures.py            # dry run: prints what would change
    python work/rebuild_signatures.py --apply    # writes the library and the DB (back both up first)
"""
import cv2, json, os, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from sqlalchemy import select
from app.store import Store
from app.db.models import Match, Medal
from signatures import Library
from result_parser import banner_identify
from medals import parse_medals


def rebuild(apply=False):
    st = Store(); lib = Library(); old_ids = list(lib.items)
    lib.items = {k: it for k, it in lib.items.items() if it['kind'] == 'panel_weapon'}   # learnt from scoreboards (panel.py), not from these screens
    log = dict(banners=0, medals=0, medals_added=0, medals_unmatched=0, columns_filled=0, conflicts=[], renamed=[])
    votes = {}; pending = []                                     # medal sig id -> Counter(stored name); Medal rows to name
    with st.Session.begin() as s:
        for m in s.scalars(select(Match).order_by(Match.id)):
            raw = json.loads(m.raw_json) if m.raw_json else None
            if m.result_image and raw is not None and (f := cv2.imread(os.path.join(st.root, m.result_image))) is not None:
                for kind in ('stage', 'mode', 'rule'):
                    sid, label, _ = banner_identify(f, kind, lib)
                    known = getattr(m, kind)
                    if sid and known and not label: lib.label(sid, known); label = known
                    elif known and label and known != label: log['conflicts'].append((m.id, kind, known, label))
                    if label and not known: setattr(m, kind, label); log['columns_filled'] += 1
                    raw[kind + '_id'] = sid; raw[kind] = label; log['banners'] += 1
                m.raw_json = json.dumps(raw, ensure_ascii=False)
            if m.medal_image and (f := cv2.imread(os.path.join(st.root, m.medal_image))) is not None:
                rows = {d.position: d for d in m.medals}
                for md in parse_medals(f, lib):                  # names are assigned per cluster below, once all screens are read
                    d = rows.pop(md['position'], None)
                    if d is None: d = Medal(name=md['sig_id'], rank=md['rank'], position=md['position']); m.medals.append(d); log['medals_added'] += 1
                    else: log['medals'] += 1
                    votes.setdefault(md['sig_id'], Counter())[d.name if d.name and d.name not in (d.sig_id, md['sig_id']) else None] += 1
                    d.sig_id = md['sig_id']; pending.append(d)
                log['medals_unmatched'] += len(rows)             # stored medals the new code did not find: kept as they are
        # medal clusters: the stored names are not trusted one by one (the old signature confused No.1 / No.2), the
        # cluster takes the name most of its screens were stored under; the rest are renamed and listed. A name claimed
        # by several clusters goes to the biggest one, the others stay unlabelled (they are some other text: name them in the UI)
        claims = {}
        for sid, c in votes.items():
            name = max((n for n in c if n), key=c.__getitem__, default=None)
            if name: claims.setdefault(name, []).append((sum(c.values()), sid))
            if len([n for n in c if n]) > 1: log['conflicts'].append(('medal cluster', sid, dict(c), '->', name))
        for name, cl in claims.items():
            cl.sort(reverse=True); lib.label(cl[0][1], name)
            for n, sid in cl[1:]: print(f'  UNLABELLED: {n} medal(s) stored as {name!r} are a different text (signature {sid}); name them in the UI')
        for d in pending:
            new = lib.items[d.sig_id].get('label') or d.sig_id
            if d.name and d.name != new: log['renamed'].append((d.match_id, d.position, d.name, '->', new))
            d.name = new
        print(f"{log['banners']} banners, {log['medals']} medals re-pointed, {log['medals_added']} medals added, "
              f"{log['medals_unmatched']} stored medals not found again, {log['columns_filled']} empty columns filled")
        for r in log['renamed']: print('  medal renamed:', r)
        print(f"library: {len(old_ids)} -> {len(lib.items)} signatures, "
              f"{sum(1 for it in lib.items.values() if not it.get('label'))} unlabelled")
        for c in log['conflicts']: print('  CONFLICT (kept the DB value, not relabelled):', c)
        if not apply:
            s.rollback(); print('dry run: nothing written (--apply to write)'); return
        lib.save(drop=old_ids)
    st.events.publish('signatures_changed', {'rebuilt': len(lib.items)}); st.close()
    print('written:', lib.path, 'and', st.db_path)


if __name__ == '__main__':
    rebuild(apply='--apply' in sys.argv)
