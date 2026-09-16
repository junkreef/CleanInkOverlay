"""DB maintenance from the command line (replaces the old `python work/db.py ...`).

    uv run python -m app.db init      [--db PATH]   # create / migrate the file and load the weapon master
    uv run python -m app.db upgrade   [--db PATH]   # migrate to the newest schema revision (backs up a pre-ORM file first)
    uv run python -m app.db current   [--db PATH]   # print the file's revision and the code's head revision
    uv run python -m app.db stats     [--db PATH]   # print the stat tables the web shows
    uv run python -m app.db matches   [--db PATH]   # list my matches
New schema revisions: edit app/db/models.py, then `uv run alembic revision --autogenerate -m "..."` (see alembic.ini).
"""
import argparse, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path: sys.path.insert(0, ROOT)
from app.db import DEFAULT_DB, make_engine, make_session_factory, upgrade, current_revision, head_revision
from app.db import queries
from app.db.weapons import load_weapon_master


def print_rows(title, rows):
    print(f'-- {title} ({len(rows)} rows)')
    if rows:
        print('  ' + ' | '.join(rows[0].keys()))
        for r in rows: print('  ' + ' | '.join(str(v) for v in r.values()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['init', 'upgrade', 'current', 'stats', 'matches'])
    ap.add_argument('--db', default=DEFAULT_DB)
    a = ap.parse_args(); db = os.path.abspath(a.db)
    if a.cmd == 'current':
        print(f'{db}: {current_revision(db) or "(pre-ORM or missing)"}   head: {head_revision()}'); return
    before, after = upgrade(db)
    if before == after: print(f'[db] {os.path.basename(db)}: schema {after} (up to date)')
    if a.cmd in ('init', 'upgrade'):
        if a.cmd == 'init':
            with make_session_factory(make_engine(db))() as s: print('weapons:', load_weapon_master(s))
        return
    with make_session_factory(make_engine(db))() as s:
        if a.cmd == 'stats':
            for name, rows in queries.stats(s).items(): print_rows(name, rows)
        elif a.cmd == 'matches':
            print_rows('my_matches', queries.rows(s, queries.match_row().order_by(queries.Match.id)))


if __name__ == '__main__':
    main()
