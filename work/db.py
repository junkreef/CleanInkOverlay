"""SQLite store for match results and in-match timelines.

    python work/db.py init            # create data/splatoon.db (+ weapon master from the wiki sections)
    python work/db.py stats           # print the built-in stat views
    python work/db.py matches         # list my matches

Design (ナワバリ first; ranked columns exist but stay NULL):
  matches        one row per match: when, stage/mode/rule, win/lose, paint %, image paths
  match_players  8 rows per match in HUD slot order (0-3 ally, 4-7 enemy): weapon + result-screen stats
  events         timeline: t_ms from timer start; death (any slot, HUD), kill (self -> target),
                 killed_by (killer -> self), special
  weapons        master from the wiki sections (class), used for grouping
Player names are not recorded (random matchmaking, and labelling them was never used): players are identified
within a match by HUD slot and weapon only. DBs created before 2026-09-15 still carry the unused columns
match_players.name / name_sig_id (drop them by hand: ALTER TABLE match_players DROP COLUMN ...).
"""
import os, sqlite3, sys, json
sys.path.insert(0, os.path.dirname(__file__))

ROOT = os.path.join(os.path.dirname(__file__), '..')
DB = os.path.join(ROOT, 'data', 'splatoon.db')

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS matches (
  id            INTEGER PRIMARY KEY,
  started_at    TEXT NOT NULL,                -- local ISO time of timer start (t=0)
  ended_at      TEXT,
  mode          TEXT,                         -- レギュラーマッチ / バンカラマッチ ...
  rule          TEXT,                         -- ナワバリバトル / ガチエリア ...
  stage         TEXT,
  result        TEXT CHECK (result IN ('win', 'lose', 'draw')),
  my_pct        REAL,                         -- ナワバリ: 塗りポイント %
  enemy_pct     REAL,
  my_count      INTEGER,                      -- ガチ (future)
  enemy_count   INTEGER,
  knockout      INTEGER,                      -- 1 = KO (future)
  duration_s    REAL,                         -- timer start -> Finish
  source        TEXT,                         -- 'live' or the video file name
  rule_image    TEXT,                         -- saved PNG of the rule screen
  result_image  TEXT,                         -- saved PNG of the result screen
  medal_image   TEXT,                         -- saved PNG of the 表彰 screen
  raw_json      TEXT,                         -- full parser output for re-analysis
  notes         TEXT
);
CREATE TABLE IF NOT EXISTS match_players (
  match_id      INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  slot          INTEGER NOT NULL,             -- HUD slot 0-7 = rule-screen card order (0-3 ally, 4-7 enemy)
  team          TEXT NOT NULL CHECK (team IN ('ally', 'enemy')),
  is_self       INTEGER NOT NULL DEFAULT 0,
  weapon        TEXT,                         -- NULL when below the unknown threshold
  weapon_score  REAL,
  weapon_conf   REAL,
  points        INTEGER,
  kills_assists INTEGER,
  deaths        INTEGER,
  specials      INTEGER,
  result_row    INTEGER,                      -- 0-3 position inside the team's result panel (points order)
  link_score    REAL,                         -- HUD slot <-> result row weapon-icon correlation (NULL = slot order arbitrary)
  PRIMARY KEY (match_id, slot)
);
CREATE TABLE IF NOT EXISTS events (
  id            INTEGER PRIMARY KEY,
  match_id      INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  t_ms          INTEGER NOT NULL,             -- since timer start
  clock         TEXT,                         -- remaining time as shown ('2:38')
  type          TEXT NOT NULL CHECK (type IN ('death', 'kill', 'killed_by', 'special')),
  slot          INTEGER,                      -- subject: death -> who died, kill/killed_by -> self, special -> who used it
  target_slot   INTEGER,                      -- kill -> victim, killed_by -> killer
  weapon        TEXT,                         -- killed_by: weapon named in the bubble (when read)
  source        TEXT,                         -- hud / killfeed / bubble / respawn
  confidence    REAL,
  duration_ms   INTEGER
);
CREATE INDEX IF NOT EXISTS events_match ON events(match_id, t_ms);
CREATE TABLE IF NOT EXISTS medals (
  match_id      INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,                -- label, or the signature id until labelled
  rank          TEXT,                         -- gold / silver
  position      INTEGER,                      -- 0-2, top to bottom on the 表彰 screen
  sig_id        TEXT
);
CREATE TABLE IF NOT EXISTS weapons (
  name          TEXT PRIMARY KEY,
  class         TEXT                          -- シューター / ローラー / チャージャー ... (wiki section)
);

CREATE VIEW IF NOT EXISTS my_matches AS
  SELECT m.id, m.started_at, m.stage, m.mode, m.rule, m.result, m.my_pct, m.enemy_pct,
         p.weapon, p.points, p.kills_assists, p.deaths, p.specials
  FROM matches m JOIN match_players p ON p.match_id = m.id AND p.is_self = 1;

CREATE VIEW IF NOT EXISTS weapon_stats AS               -- 自分の武器別
  SELECT weapon, COUNT(*) AS games, SUM(result = 'win') AS wins,
         ROUND(100.0 * SUM(result = 'win') / COUNT(*), 1) AS win_pct,
         ROUND(AVG(kills_assists), 2) AS avg_ka, ROUND(AVG(deaths), 2) AS avg_d, ROUND(AVG(specials), 2) AS avg_sp,
         ROUND(AVG(points)) AS avg_points
  FROM my_matches GROUP BY weapon ORDER BY games DESC;

CREATE VIEW IF NOT EXISTS stage_stats AS                -- ステージ別
  SELECT stage, COUNT(*) AS games, SUM(result = 'win') AS wins,
         ROUND(100.0 * SUM(result = 'win') / COUNT(*), 1) AS win_pct,
         ROUND(AVG(kills_assists), 2) AS avg_ka, ROUND(AVG(deaths), 2) AS avg_d, ROUND(AVG(points)) AS avg_points
  FROM my_matches GROUP BY stage ORDER BY games DESC;

CREATE VIEW IF NOT EXISTS enemy_weapon_stats AS         -- 相手の武器別: 遭遇数、遭遇時の勝率、やられた/たおした回数
  SELECT p.weapon, COUNT(*) AS seen, SUM(m.result = 'win') AS wins,
         ROUND(100.0 * SUM(m.result = 'win') / COUNT(*), 1) AS win_pct,
         (SELECT COUNT(*) FROM events e JOIN match_players k ON k.match_id = e.match_id AND k.slot = e.target_slot
          WHERE e.type = 'killed_by' AND k.weapon = p.weapon) AS killed_me,
         (SELECT COUNT(*) FROM events e JOIN match_players v ON v.match_id = e.match_id AND v.slot = e.target_slot
          WHERE e.type = 'kill' AND v.weapon = p.weapon) AS i_killed
  FROM match_players p JOIN matches m ON m.id = p.match_id
  WHERE p.team = 'enemy' AND p.weapon IS NOT NULL GROUP BY p.weapon ORDER BY seen DESC;

CREATE VIEW IF NOT EXISTS medal_stats AS                -- 表彰の種類別
  SELECT name, rank, COUNT(*) AS n FROM medals GROUP BY name, rank ORDER BY n DESC;

CREATE VIEW IF NOT EXISTS my_timeline AS                -- 自分のキル/デスを 30 秒刻みで
  SELECT (e.t_ms / 30000) * 30 AS from_s, e.type, COUNT(*) AS n
  FROM events e JOIN match_players p ON p.match_id = e.match_id AND p.slot = e.slot AND p.is_self = 1
  WHERE e.type IN ('kill', 'killed_by', 'death') GROUP BY from_s, e.type ORDER BY from_s, e.type;
"""


def connect(path=DB):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False); con.executescript(SCHEMA); con.row_factory = sqlite3.Row   # the store serialises access with a lock
    for tbl, col, typ in MIGRATIONS:                       # columns added after the first DBs were created
        try: con.execute(f'ALTER TABLE {tbl} ADD COLUMN {col} {typ}')
        except sqlite3.OperationalError: pass
    con.commit()
    return con


MIGRATIONS = [('matches', 'medal_image', 'TEXT'), ('medals', 'position', 'INTEGER'), ('medals', 'sig_id', 'TEXT')]


def _insert(con, table, row):
    cols = list(row)
    return con.execute(f'INSERT INTO {table} ({",".join(cols)}) VALUES ({",".join("?" * len(cols))})', [row[c] for c in cols])


def insert_match(con, match, players, events, medals=()):
    """match: matches columns; players: match_players dicts (without match_id); events: events dicts. Returns match id."""
    mid = _insert(con, 'matches', {k: v for k, v in match.items() if k != 'id'}).lastrowid
    for p in players: _insert(con, 'match_players', dict(p, match_id=mid))
    for e in events: _insert(con, 'events', dict(e, match_id=mid))
    for md in medals:                                    # dicts from medals.parse_medals
        _insert(con, 'medals', dict(match_id=mid, name=md.get('name') or md.get('sig_id'), rank=md.get('rank'), position=md.get('position'), sig_id=md.get('sig_id')))
    con.commit()
    return mid


CLASSES = ['シューター', 'ローラー', 'チャージャー', 'スロッシャー', 'スピナー', 'マニューバー', 'シェルター', 'ブラスター', 'フデ', 'ストリンガー', 'ワイパー']
SECTION_STARTS = {'スプラッシュボム': 'サブ', 'ウルトラショット': 'スペシャル', 'ガチホコ': 'その他'}


def load_weapon_master(con):
    """wiki ブキ section is one flat list: class icon, then its weapons; subs / specials / misc follow the mains"""
    from weapon_match import icon_name
    sec = os.path.join(ROOT, 'assets', 'weapon_icons_sections.json')
    if not os.path.exists(sec): return 0
    names = [icon_name(x) for x in json.load(open(sec, encoding='utf-8'))['ブキ'] if '_フチ' not in x]
    cls = None; n = 0
    for name in names:
        if name in SECTION_STARTS: cls = SECTION_STARTS[name]
        if name in CLASSES: cls = name; continue          # the class icon itself is not a weapon
        con.execute('INSERT OR REPLACE INTO weapons (name, class) VALUES (?, ?)', (name, cls)); n += 1
    con.commit(); return n


def print_view(con, view):
    rows = con.execute(f'SELECT * FROM {view}').fetchall()
    print(f'-- {view} ({len(rows)} rows)')
    if rows:
        print('  ' + ' | '.join(rows[0].keys()))
        for r in rows: print('  ' + ' | '.join(str(v) for v in r))


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'init'
    con = connect()
    if cmd == 'init':
        print('created', os.path.abspath(DB), 'weapons:', load_weapon_master(con))
    elif cmd == 'stats':
        for v in ('weapon_stats', 'stage_stats', 'enemy_weapon_stats', 'medal_stats', 'my_timeline'): print_view(con, v)
    elif cmd == 'matches':
        print_view(con, 'my_matches')
