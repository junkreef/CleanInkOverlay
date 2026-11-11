"""Component 1 - the data store: the ONLY code that opens the SQLite DB and reads/writes the data files
(match images under samples/, the signature library for stages / medals).

It is a plain Python module, not a network server: the recorder and the web backend import it. Both can
run in one process (the backend starts the recorder as a thread) or separately (SQLite in WAL mode).
The DB layer is SQLAlchemy (models / queries / migrations live in app/db). A missing file is created at the
current schema; an existing file whose schema is behind is refused with a message, and migrated only when
asked: `uv run python -m app.db upgrade` (backs up the file next to itself first; the release launcher,
app.launch, asks for it at every start).
Everything the store writes is under its `root`, the data folder (app.paths.DATA_ROOT). In a git checkout that is
the repo root and the libraries are the files under assets/. In a release the program folder is read-only: the
shipped libraries are read from there and what the user adds goes to the same paths under the data folder.
In-process notifications go through `store.events` (subscribe(topic, callback) / publish): topics are
'match_saved' {id}, 'match_deleted' {id}, 'signatures_changed' {}.

    from app.store import Store
    s = Store()                      # data/splatoon.db under the data folder
    s.list_matches(); s.get_match(3); s.label_signature('s_ca328fa4', 'タカアシ経済特区')

Old screen images are deleted by `Store.prune_images` (the backend runs it at startup; by hand:
`uv run python -m app.store prune-images [--days N] [--dry]`; N defaults to config.toml's images.keep_days, itself 7).
"""
import os, sys, json, threading, time
import numpy as np
import cv2
from sqlalchemy import delete, func, select, update

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
WORK = os.path.join(ROOT, 'work')
if ROOT not in sys.path: sys.path.insert(0, ROOT)
if WORK not in sys.path: sys.path.insert(0, WORK)
from app.paths import DATA_ROOT, SPLIT, ASSETS
from app.db import make_engine, make_session_factory, upgrade, require_current, Match, MatchPlayer, Event, Medal, Timeline, Weapon
from app.db import queries
from app.db.weapons import load_weapon_master
from signatures import Library
from weapon_icons import IconLibrary, group_name


class Events:
    """tiny in-process event bus; callbacks run on the publishing thread"""
    def __init__(self):
        self._subs = {}; self._lock = threading.Lock()

    def subscribe(self, topic, callback):
        with self._lock: self._subs.setdefault(topic, []).append(callback)
        return lambda: self.unsubscribe(topic, callback)

    def unsubscribe(self, topic, callback):
        with self._lock:
            if callback in self._subs.get(topic, []): self._subs[topic].remove(callback)

    def publish(self, topic, payload=None):
        with self._lock: subs = list(self._subs.get(topic, []))
        for cb in subs:
            try: cb(payload or {})
            except Exception as e: print(f'[events] {topic} subscriber failed: {e!r}', flush=True)


class Store:
    def __init__(self, root=None, db_path=None, images_dir='samples/matches', shipped_assets=None):
        """root: the data folder (default app.paths.DATA_ROOT). shipped_assets: the program's assets folder when the
        libraries under root/assets only hold the user's additions (default: so for a release, where the two differ)"""
        if root is None:
            root = DATA_ROOT
            if shipped_assets is None and SPLIT: shipped_assets = ASSETS
        self.root = root
        self.shipped_assets = shipped_assets
        self.db_path = db_path or os.path.join(root, 'data', 'splatoon.db')
        self.images_dir = os.path.join(root, images_dir)
        self.misses_dir = os.path.join(root, 'samples', 'misses')
        self.bubbles_dir = os.path.join(root, 'samples', 'bubbles')
        self.events = Events()
        self._lock = threading.RLock()                       # serialises the writers of this process
        if not os.path.exists(self.db_path) or os.path.getsize(self.db_path) == 0:
            upgrade(self.db_path)                            # a new file is created at the current schema
        else:
            require_current(self.db_path)                    # an existing file is migrated only on request (python -m app.db upgrade)
        self.engine = make_engine(self.db_path)
        self.Session = make_session_factory(self.engine)
        with self._lock, self.Session() as s: load_weapon_master(s)   # assets/weapons.json: names to offer, classes for the stats
        self._sig = None
        self._icons = None

    # ------------------------------------------------------------------ libraries (owned here, handed out to the analysers)
    def rel(self, path):
        """path relative to the data folder, with forward slashes (what the DB stores and the web serves)"""
        return os.path.relpath(path, self.root).replace(os.sep, '/')

    def _shipped(self, name):
        return os.path.join(self.shipped_assets, name) if self.shipped_assets else None

    def signatures(self):
        if self._sig is None:
            with self._lock:
                if self._sig is None:
                    lib = Library(os.path.join(self.root, 'assets', 'signatures.json'), shipped=self._shipped('signatures.json'))
                    if lib.adopted:                          # a newer release names what was unknown here: fill the matches too
                        with self.Session.begin() as s:
                            for sid in lib.adopted: self._fill_label(s, sid, lib.items[sid]['kind'], lib.items[sid]['label'])
                        lib.save()
                    self._sig = lib
        return self._sig

    def weapon_icons(self):
        """weapon icon templates cut from our result screens (assets/weapon_icons_captured) and their samples (data/icon_samples)"""
        if self._icons is None:
            with self._lock:
                if self._icons is None:
                    self._icons = IconLibrary(os.path.join(self.root, 'assets', 'weapon_icons_captured'), os.path.join(self.root, 'data', 'icon_samples'),
                                              shipped_dir=self._shipped('weapon_icons_captured'))
        return self._icons

    def save_libraries(self):
        with self._lock:
            if self._sig is not None: self._sig.save()
            if self._icons is not None: self._icons.save()

    # ------------------------------------------------------------------ files
    def save_image(self, stamp, kind, frame):
        """PNG of a screen (rule / result / medals) -> path relative to the data folder"""
        os.makedirs(self.images_dir, exist_ok=True)
        p = os.path.join(self.images_dir, f'{stamp}_{kind}.png'); cv2.imencode('.png', frame)[1].tofile(p)
        return self.rel(p)

    def save_json(self, stamp, name, obj):
        os.makedirs(self.images_dir, exist_ok=True)
        p = os.path.join(self.images_dir, f'{stamp}{name}.json')
        json.dump(obj, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
        return self.rel(p)

    def save_evidence(self, name, sheet):
        """contact sheet for a suspected miss (own death without a bubble) -> path relative to the data folder"""
        os.makedirs(self.misses_dir, exist_ok=True)
        p = os.path.join(self.misses_dir, name + '.jpg'); cv2.imencode('.jpg', sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(p)
        return self.rel(p)

    def save_bubble(self, name, sheet):
        """best killer-card crop of a death bubble + the frame it came from -> path relative to the data folder"""
        os.makedirs(self.bubbles_dir, exist_ok=True)
        p = os.path.join(self.bubbles_dir, name + '.jpg'); cv2.imencode('.jpg', sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tofile(p)
        return self.rel(p)

    def prune_images(self, keep_days=7, dry=False):
        """delete screen PNGs (samples/matches) and bubble / miss evidence JPGs older than `keep_days` (file mtime), so the
        folders stop growing. Kept: the screens that show an unlabelled signature (the labelling page needs them) and the
        per-match JSON. Match rows pointing at a deleted screen get that column cleared.
        Returns the deleted paths, relative to the data folder (what would be deleted when dry)."""
        keep = set()
        for it in self.unlabelled_signatures():
            for ex in self.signature_examples(it['id']):
                keep.update(ex.get(k) for k in ('result_image', 'medal_image', 'rule_image') if ex.get(k))
        cutoff = time.time() - keep_days * 86400; gone = []
        for d, ext in ((self.images_dir, '.png'), (self.bubbles_dir, '.jpg'), (self.misses_dir, '.jpg')):
            if not os.path.isdir(d): continue
            for name in os.listdir(d):
                p = os.path.join(d, name); r = os.path.relpath(p, self.root).replace(os.sep, '/')
                if not name.endswith(ext) or r in keep or os.path.getmtime(p) >= cutoff: continue
                gone.append(r)
                if not dry: os.remove(p)
        if gone and not dry:
            with self._lock, self.Session.begin() as s:
                for col in (Match.rule_image, Match.result_image, Match.medal_image):
                    s.execute(update(Match).where(col.in_(gone)).values({col.key: None}))
        return gone

    def file_path(self, relpath):
        """absolute path of a data file the web may serve; None if outside the allowed folders"""
        p = os.path.abspath(os.path.join(self.root, relpath))
        allowed = [os.path.join(self.root, 'samples'), os.path.join(self.root, 'work', 'frames'), self.weapon_icons().samples_dir]
        if not any(p.startswith(os.path.abspath(a) + os.sep) for a in allowed): return None
        return p if os.path.exists(p) else None

    def read_image(self, relpath):
        p = self.file_path(relpath)
        return cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR) if p else None

    # ------------------------------------------------------------------ matches
    def insert_match(self, match, players, events, medals=(), timeline=()):
        """match: matches columns; players: match_players dicts (without match_id); events: events dicts; medals: dicts from
        medals.parse_medals; timeline: per-second dicts (t_s, points, gauge, ready, obj_pos, obj_holder, my_best, enemy_best, my_count, enemy_count, my_penalty, enemy_penalty, overtime). Returns the match id."""
        m = Match(**{k: v for k, v in match.items() if k != 'id'})
        m.players = [MatchPlayer(**p) for p in players]
        m.events = [Event(**e) for e in events]
        m.timeline = [Timeline(**r) for r in timeline]
        m.medals = [Medal(name=md.get('name') or md.get('sig_id'), rank=md.get('rank'), position=md.get('position'), sig_id=md.get('sig_id'))
                    for md in medals]
        with self._lock, self.Session.begin() as s:
            s.add(m); s.flush(); mid = m.id
        self.events.publish('match_saved', {'id': mid})
        return mid

    def delete_match(self, mid):
        with self._lock, self.Session.begin() as s:
            s.execute(delete(Match).where(Match.id == mid))   # players / events / medals / timeline go by ON DELETE CASCADE
        self.events.publish('match_deleted', {'id': mid})

    def last_match_id(self):
        with self.Session() as s:
            return s.scalar(select(func.coalesce(func.max(Match.id), 0)))

    def list_matches(self, limit=50, offset=0):
        """newest first, with the player's own row (weapon, k/a/d/sp) and the medal / event counts"""
        n_medals = select(func.count()).where(Medal.match_id == Match.id).scalar_subquery().label('medals')
        n_events = select(func.count()).where(Event.match_id == Match.id).scalar_subquery().label('events')
        with self.Session() as s:
            return queries.rows(s, queries.match_row(n_medals, n_events).order_by(Match.id.desc()).limit(limit).offset(offset))

    def get_match(self, mid):
        with self.Session() as s:
            m = s.get(Match, mid)
            if m is None: return None
            out = m.to_dict(exclude=('raw_json',))
            out['players'] = [p.to_dict() for p in m.players]
            out['events'] = [e.to_dict() for e in m.events]
            out['medals'] = [d.to_dict() for d in m.medals]
            out['timeline'] = [{k: v for k, v in r.to_dict().items() if k != 'match_id'} for r in m.timeline]
        return out

    def stats(self, since=None, mode=None, rule=None):
        """the stat tables (optionally only matches started at/after `since` / of one `mode` / `rule`, queries.GACHI = every
        ガチ rule), my newest results, and the modes / rules there are to pick from"""
        with self.Session() as s:
            out = queries.stats(s, since, mode, rule)
            out['recent'] = queries.rows(s, queries.recent_results(since=since, mode=mode, rule=rule))
            out['modes'] = list(s.scalars(select(Match.mode).where(Match.mode.is_not(None)).distinct().order_by(Match.mode)))
            out['rules'] = list(s.scalars(select(Match.rule).where(Match.rule.is_not(None)).distinct().order_by(Match.rule)))
        return out

    def overlay(self, since=None, limit=8):
        """data for the stream overlay: session totals (matches started at/after `since`, ISO local time; None = everything),
        the newest matches with my row + medals, and all-time counts"""
        q = queries.match_row()
        if since: q = q.where(Match.started_at >= since)
        with self.Session() as s:
            rows = queries.rows(s, q.order_by(Match.id.desc()))
            recent = rows[:limit]
            for m in recent:
                m['medals'] = queries.rows(s, select(Medal.name, Medal.rank, Medal.position).where(Medal.match_id == m['id']).order_by(Medal.position))
            n_all, wins_all = s.execute(queries.match_counts()).one()
            killed_by = queries.rows(s, queries.killed_by_weapons(since))
        wins = sum(m['result'] == 'win' for m in rows); losses = sum(m['result'] == 'lose' for m in rows)
        streak = {'kind': None, 'n': 0}
        for m in rows:                                       # newest first: same result as the newest match, until it changes
            if m['result'] not in ('win', 'lose'): break
            if streak['kind'] is None: streak['kind'] = m['result']
            if m['result'] != streak['kind']: break
            streak['n'] += 1
        tot = lambda k: sum(m[k] or 0 for m in rows if m[k] is not None)
        decided = wins + losses
        session = {'since': since, 'matches': len(rows), 'wins': wins, 'losses': losses, 'draws': len(rows) - decided,
                   'win_pct': round(100.0 * wins / decided, 1) if decided else None, 'streak': streak,
                   'kills_assists': tot('kills_assists'), 'deaths': tot('deaths'), 'specials': tot('specials'), 'points': tot('points'),
                   'weapons': sorted({m['weapon'] for m in rows if m['weapon']}), 'results': [m['result'] for m in rows[:30]], 'killed_by': killed_by,
                   'best_ka': max((m['kills_assists'] or 0 for m in rows), default=0), 'best_points': max((m['points'] or 0 for m in rows), default=0)}
        return {'session': session, 'recent': recent, 'last': recent[0] if recent else None, 'all_time': {'matches': n_all, 'wins': wins_all}}

    def summary(self):
        with self.Session() as s:
            n, wins = s.execute(queries.match_counts()).one()
        return {'matches': n, 'wins': wins, 'last_id': self.last_match_id(),
                'unlabelled_signatures': len(self.unlabelled_signatures()), 'unknown_weapon_icons': len(self.weapon_icons().groups())}

    # ------------------------------------------------------------------ signature labelling (stages / medals)
    def unlabelled_signatures(self, kind=None):
        lib = self.signatures()
        return [{'id': k, 'kind': it['kind']} for k, it in lib.items.items() if not it.get('label') and (kind is None or it['kind'] == kind)]

    def label_signature(self, sid, label):
        lib = self.signatures()
        if sid not in lib.items: raise KeyError(sid)
        with self._lock, self.Session.begin() as s:
            lib.label(sid, label); lib.save()
            self._fill_label(s, sid, lib.items[sid]['kind'], label)
        self.events.publish('signatures_changed', {'id': sid})

    @staticmethod
    def _fill_label(s, sid, kind, label):
        """medals / stages / modes / rules already stored under the id become readable"""
        s.execute(update(Medal).where(Medal.sig_id == sid).values(name=label))
        if kind in ('stage', 'mode', 'rule', 'title'):                      # title = the rule name on the rule screen: fills rule too
            col = getattr(Match, 'rule' if kind == 'title' else kind)
            s.execute(update(Match).where(col.is_(None), Match.raw_json.like(f'%"{kind}_id": "{sid}"%')).values({col.key: label}))

    def signature_examples(self, sid, limit=3):
        """where an unlabelled signature was seen: match ids + image paths (medal screen / rule + result screen) for showing it to a human"""
        with self.Session() as s:
            rows = queries.rows(s, select(Medal.match_id, Medal.position, Match.medal_image).join(Match, Match.id == Medal.match_id)
                                   .where(Medal.sig_id == sid).order_by(Medal.match_id.desc()).limit(limit))
            if rows: return rows
            kind = {'s': 'stage', 'm': 'mode', 'r': 'rule', 't': 'title'}.get(sid[:1])   # stage / mode / rule / title ids live in raw_json
            if kind is None: return []
            return queries.rows(s, select(Match.id.label('match_id'), Match.rule_image, Match.result_image)
                                   .where(Match.raw_json.like(f'%"{kind}_id": "{sid}"%')).order_by(Match.id.desc()).limit(limit))

    # ------------------------------------------------------------------ unknown weapon icons (named like the signatures)
    def unknown_weapon_icons(self, limit=3):
        """the unknown icon groups: id, the wiki's guess (None for an icon nothing matched), their sample crops (paths
        relative to the data folder) and where they were seen (match id, row, result screen), newest first"""
        lib = self.weapon_icons(); out = []
        with self.Session() as s:
            for gid in lib.groups():
                d = os.path.join(lib.samples_dir, group_name(gid))
                samples = [self.rel(os.path.join(d, st + '.png')) for st in lib.sample_stems(group_name(gid)) if os.path.exists(os.path.join(d, st + '.png'))]
                seen = []
                for mid, img, raw in s.execute(select(Match.id, Match.result_image, Match.raw_json).where(Match.raw_json.like(f'%"weapon_unknown": "{gid}"%'))
                                               .order_by(Match.id.desc()).limit(limit)):
                    rows = [r['row'] for r in json.loads(raw)['rows'] if r.get('weapon_unknown') == gid]
                    seen.append({'match_id': mid, 'result_image': img, 'rows': rows})
                out.append({'id': gid, 'guess': lib.guess(gid), 'samples': samples, 'seen': seen})
        return out

    def link_weapon_unknown(self, result_image, row, gid):
        """mark a stored match's result row as showing unknown icon group `gid` (for groups made from screens already
        stored, work/confirm_backfill.py); returns the match id or None"""
        with self._lock, self.Session.begin() as s:
            m = s.scalars(select(Match).where(Match.result_image == result_image)).first()
            if m is None or not m.raw_json: return None
            raw = json.loads(m.raw_json)
            for r in raw['rows']:
                if r['row'] == row: r['weapon_unknown'] = gid
            m.raw_json = json.dumps(raw, ensure_ascii=False)
            return m.id

    def weapon_names(self):
        """main weapon names to offer when naming an icon: the weapon master (DB) and the names we have templates for"""
        with self.Session() as s:
            names = set(s.scalars(select(Weapon.name).where(Weapon.class_.not_in(('サブ', 'スペシャル', 'その他')) | Weapon.class_.is_(None))))
        names |= {n for n in self.weapon_icons().templates if not n.startswith('_')}
        return sorted(names - {'ブキ無し'})

    def label_weapon_icon(self, gid, name):
        """an unknown icon group is `name`: its samples become (part of) the weapon's template, and the matches that saw it
        get the weapon in match_players (the row's team + position) and in raw_json, also where the wiki's guess stood"""
        if not name or name.startswith('_'): raise ValueError(name)
        lib = self.weapon_icons()
        with self._lock, self.Session.begin() as s:
            lib.label_group(gid, name); lib.save()
            for m in s.scalars(select(Match).where(Match.raw_json.like(f'%"weapon_unknown": "{gid}"%'))):
                raw = json.loads(m.raw_json)
                for ri, r in enumerate(raw['rows']):
                    if r.get('weapon_unknown') != gid: continue
                    r['weapon'] = name
                    if r.get('hteam'):
                        s.execute(update(MatchPlayer).where(MatchPlayer.match_id == m.id, MatchPlayer.team == r['hteam'],
                                                            MatchPlayer.result_row == ri % 4).values(weapon=name))
                m.raw_json = json.dumps(raw, ensure_ascii=False)
        self.events.publish('weapon_icons_changed', {'id': gid, 'name': name})

    def prune_signatures(self):
        """drop unlabelled signatures that no saved screen shows any more (dry runs, deleted matches, missing PNGs):
        the next time that text appears in a stored match it is registered again, this time with its image. Returns the ids."""
        lib = self.signatures(); gone = []
        for it in self.unlabelled_signatures():
            seen = self.signature_examples(it['id'], limit=50)
            if not any(ex.get(k) and os.path.exists(os.path.join(self.root, ex[k])) for ex in seen for k in ('result_image', 'medal_image', 'rule_image')):
                gone.append(it['id'])
        if gone:
            with self._lock:
                for sid in gone: lib.items.pop(sid, None)
                lib.save(drop=gone)
            self.events.publish('signatures_changed', {'pruned': len(gone)})
        return gone

    def close(self):
        self.engine.dispose()


def main():
    import argparse
    ap = argparse.ArgumentParser(description='delete old screen / evidence images (see Store.prune_images)')
    ap.add_argument('cmd', choices=['prune-images']); ap.add_argument('--db')
    ap.add_argument('--days', type=float, default=None, help="default: config.toml's images.keep_days (7 without it)")
    ap.add_argument('--dry', action='store_true', help='only list what would be deleted')
    a = ap.parse_args(); s = Store(db_path=os.path.abspath(a.db) if a.db else None)
    from app import config
    days = a.days if a.days is not None else config.image_keep_days()
    gone = s.prune_images(keep_days=days, dry=a.dry); s.close()
    size = sum(os.path.getsize(os.path.join(s.root, p)) for p in gone) if a.dry else None
    print(f"{'would delete' if a.dry else 'deleted'} {len(gone)} images older than {days:g} days" + (f' ({size / 2**20:.0f} MB)' if size is not None else ''))


if __name__ == '__main__':
    main()
