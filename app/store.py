"""Component 1 - the data store: the ONLY code that opens the SQLite DB and reads/writes the data files
(match images under samples/, the signature library for stages / medals).

It is a plain Python module, not a network server: the recorder and the web backend import it. Both can
run in one process (the backend starts the recorder as a thread) or separately (SQLite in WAL mode).
In-process notifications go through `store.events` (subscribe(topic, callback) / publish): topics are
'match_saved' {id}, 'match_deleted' {id}, 'signatures_changed' {}.

    from app.store import Store
    s = Store()                      # data/splatoon.db under the repo root
    s.list_matches(); s.get_match(3); s.label_signature('s_ca328fa4', 'タカアシ経済特区')
"""
import os, sys, json, glob, threading, sqlite3
import numpy as np
import cv2

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
WORK = os.path.join(ROOT, 'work')
if WORK not in sys.path: sys.path.insert(0, WORK)
import db as dbmod                                        # schema + SQL helpers (no file access of its own)
from signatures import Library


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


def rel(path):
    """repo-relative path with forward slashes (what the DB stores and the web serves)"""
    return os.path.relpath(path, ROOT).replace(os.sep, '/')


class Store:
    def __init__(self, root=ROOT, db_path=None, images_dir='samples/matches'):
        self.root = root
        self.db_path = db_path or os.path.join(root, 'data', 'splatoon.db')
        self.images_dir = os.path.join(root, images_dir)
        self.misses_dir = os.path.join(root, 'samples', 'misses')
        self.events = Events()
        self._lock = threading.RLock()
        self.con = dbmod.connect(self.db_path)
        self.con.execute('PRAGMA journal_mode=WAL')
        self._sig = None

    # ------------------------------------------------------------------ libraries (owned here, handed out to the analysers)
    def signatures(self):
        if self._sig is None: self._sig = Library()
        return self._sig

    def save_libraries(self):
        with self._lock:
            if self._sig is not None: self._sig.save()

    # ------------------------------------------------------------------ files
    def save_image(self, stamp, kind, frame):
        """PNG of a screen (rule / result / medals) -> repo-relative path"""
        os.makedirs(self.images_dir, exist_ok=True)
        p = os.path.join(self.images_dir, f'{stamp}_{kind}.png'); cv2.imencode('.png', frame)[1].tofile(p)
        return rel(p)

    def save_json(self, stamp, name, obj):
        os.makedirs(self.images_dir, exist_ok=True)
        p = os.path.join(self.images_dir, f'{stamp}{name}.json')
        json.dump(obj, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
        return rel(p)

    def save_evidence(self, name, sheet):
        """contact sheet for a suspected miss (own death without a bubble) -> repo-relative path"""
        os.makedirs(self.misses_dir, exist_ok=True)
        p = os.path.join(self.misses_dir, name + '.jpg'); cv2.imencode('.jpg', sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(p)
        return rel(p)

    def file_path(self, relpath):
        """absolute path of a data file the web may serve; None if outside the allowed folders"""
        p = os.path.abspath(os.path.join(self.root, relpath))
        allowed = [os.path.join(self.root, 'samples'), os.path.join(self.root, 'work', 'frames')]
        if not any(p.startswith(os.path.abspath(a) + os.sep) for a in allowed): return None
        return p if os.path.exists(p) else None

    def read_image(self, relpath):
        p = self.file_path(relpath)
        return cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR) if p else None

    # ------------------------------------------------------------------ matches
    def insert_match(self, match, players, events, medals=()):
        with self._lock:
            mid = dbmod.insert_match(self.con, match, players, events, medals)
        self.events.publish('match_saved', {'id': mid})
        return mid

    def delete_match(self, mid):
        with self._lock:
            self.con.execute('DELETE FROM matches WHERE id = ?', (mid,)); self.con.commit()
        self.events.publish('match_deleted', {'id': mid})

    def last_match_id(self):
        with self._lock:
            return self.con.execute('SELECT COALESCE(MAX(id), 0) FROM matches').fetchone()[0]

    def list_matches(self, limit=50, offset=0):
        """newest first, with the player's own row (weapon, k/a/d/sp) and the medal count"""
        q = '''SELECT m.id, m.started_at, m.mode, m.rule, m.stage, m.result, m.my_pct, m.enemy_pct, m.duration_s, m.source, m.notes,
                      p.weapon, p.points, p.kills_assists, p.deaths, p.specials,
                      (SELECT COUNT(*) FROM medals d WHERE d.match_id = m.id) AS medals,
                      (SELECT COUNT(*) FROM events e WHERE e.match_id = m.id) AS events
               FROM matches m LEFT JOIN match_players p ON p.match_id = m.id AND p.is_self = 1
               ORDER BY m.id DESC LIMIT ? OFFSET ?'''
        with self._lock:
            return [dict(r) for r in self.con.execute(q, (limit, offset))]

    def get_match(self, mid):
        with self._lock:
            m = self.con.execute('SELECT * FROM matches WHERE id = ?', (mid,)).fetchone()
            if m is None: return None
            out = dict(m); out.pop('raw_json', None)
            out['players'] = [dict(r) for r in self.con.execute('SELECT * FROM match_players WHERE match_id = ? ORDER BY slot', (mid,))]
            out['events'] = [dict(r) for r in self.con.execute('SELECT * FROM events WHERE match_id = ? ORDER BY t_ms, id', (mid,))]
            out['medals'] = [dict(r) for r in self.con.execute('SELECT * FROM medals WHERE match_id = ? ORDER BY position', (mid,))]
        return out

    def stats(self):
        with self._lock:
            return {v: [dict(r) for r in self.con.execute(f'SELECT * FROM {v}')] for v in ('weapon_stats', 'stage_stats', 'enemy_weapon_stats', 'medal_stats', 'my_timeline')}

    def overlay(self, since=None, limit=8):
        """data for the stream overlay: session totals (matches started at/after `since`, ISO local time; None = everything),
        the newest matches with my row + medals, and all-time counts"""
        q = '''SELECT m.id, m.started_at, m.rule, m.stage, m.result, m.my_pct, m.enemy_pct, m.duration_s,
                      p.weapon, p.points, p.kills_assists, p.deaths, p.specials
               FROM matches m LEFT JOIN match_players p ON p.match_id = m.id AND p.is_self = 1'''
        with self._lock:
            rows = [dict(r) for r in self.con.execute(q + (' WHERE m.started_at >= ?' if since else '') + ' ORDER BY m.id DESC', (since,) if since else ())]
            recent = rows[:limit]
            for m in recent:
                m['medals'] = [dict(r) for r in self.con.execute('SELECT name, rank, position FROM medals WHERE match_id = ? ORDER BY position', (m['id'],))]
            n_all, wins_all = self.con.execute("SELECT COUNT(*), COALESCE(SUM(result = 'win'), 0) FROM matches").fetchone()
            killed_by = [dict(r) for r in self.con.execute('''SELECT k.weapon, COUNT(*) AS n FROM events e JOIN matches m ON m.id = e.match_id
                                                             JOIN match_players k ON k.match_id = e.match_id AND k.slot = e.target_slot
                                                             WHERE e.type = 'killed_by' AND k.weapon IS NOT NULL''' + (' AND m.started_at >= ?' if since else '') +
                                                          ' GROUP BY k.weapon ORDER BY n DESC, k.weapon LIMIT 3', (since,) if since else ())]
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
        with self._lock:
            n, wins = self.con.execute("SELECT COUNT(*), COALESCE(SUM(result = 'win'), 0) FROM matches").fetchone()
        return {'matches': n, 'wins': wins, 'last_id': self.last_match_id(),
                'unlabelled_signatures': len(self.unlabelled_signatures())}

    # ------------------------------------------------------------------ signature labelling (stages / medals)
    def unlabelled_signatures(self, kind=None):
        lib = self.signatures()
        return [{'id': k, 'kind': it['kind']} for k, it in lib.items.items() if not it.get('label') and (kind is None or it['kind'] == kind)]

    def label_signature(self, sid, label):
        lib = self.signatures()
        if sid not in lib.items: raise KeyError(sid)
        with self._lock:
            lib.label(sid, label); lib.save()
            # medals/stages already stored under the id become readable
            self.con.execute('UPDATE medals SET name = ? WHERE sig_id = ?', (label, sid))
            if lib.items[sid]['kind'] == 'stage':
                self.con.execute("UPDATE matches SET stage = ? WHERE stage IS NULL AND raw_json LIKE ?", (label, f'%"stage_id": "{sid}"%'))
            self.con.commit()
        self.events.publish('signatures_changed', {'id': sid})

    def signature_examples(self, sid, limit=3):
        """where an unlabelled signature was seen: match ids + image paths (medal screen / rule + result screen) for showing it to a human"""
        with self._lock:
            rows = self.con.execute('SELECT d.match_id, d.position, m.medal_image FROM medals d JOIN matches m ON m.id = d.match_id WHERE d.sig_id = ? ORDER BY d.match_id DESC LIMIT ?', (sid, limit)).fetchall()
            if rows: return [dict(r) for r in rows]
            kind = {'s': 'stage', 'm': 'mode', 'r': 'rule'}.get(sid[:1])             # stage / mode / rule ids live in raw_json
            if kind is None: return []
            rows = self.con.execute('SELECT id AS match_id, rule_image, result_image FROM matches WHERE raw_json LIKE ? ORDER BY id DESC LIMIT ?', (f'%"{kind}_id": "{sid}"%', limit)).fetchall()
            return [dict(r) for r in rows]

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
        with self._lock: self.con.close()
