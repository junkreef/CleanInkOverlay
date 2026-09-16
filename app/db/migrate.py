"""Bring a DB file up to the current schema (Alembic `upgrade head`), creating it when missing.

DBs written by the raw-SQL era (work/db.py, no alembic_version table) are recognised, backed up next to the
file (splatoon.db.bak-<date>-pre-orm), topped up with the columns that era added by ALTER, stamped as
revision 0001 and then migrated like any other.
Existing files are migrated only on request: `uv run python -m app.db upgrade [--db PATH]` (stop the backend
first). The store creates a missing file itself but refuses an outdated one (`require_current`).
"""
import os, shutil, sqlite3, time
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from .engine import db_url

MIGRATIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migrations')
BASELINE = '0001'
# columns work/db.py added with ALTER TABLE after the first DBs were created (a pre-ORM DB may lack them)
LEGACY_COLUMNS = [('matches', 'medal_image', 'TEXT'), ('medals', 'position', 'INTEGER'), ('medals', 'sig_id', 'TEXT')]


def alembic_config(db_path):
    cfg = Config()
    cfg.set_main_option('script_location', MIGRATIONS)
    cfg.set_main_option('db_path', os.path.abspath(db_path))
    return cfg


def current_revision(db_path):
    """revision stamped in the file, None for a pre-ORM or empty DB"""
    if not os.path.exists(db_path): return None
    engine = create_engine(db_url(db_path), poolclass=NullPool)
    with engine.connect() as con:
        return MigrationContext.configure(con).get_current_revision()


def head_revision():
    cfg = Config(); cfg.set_main_option('script_location', MIGRATIONS)
    return ScriptDirectory.from_config(cfg).get_current_head()


def _has_table(con, name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def backup(db_path, tag='pre-orm'):
    """checkpoint the WAL and copy the file: <db>.bak-YYYY-MM-DD-<tag> (a counter is added if that exists)"""
    con = sqlite3.connect(db_path)
    try: con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally: con.close()
    base = f'{db_path}.bak-{time.strftime("%Y-%m-%d")}-{tag}'; dst = base; n = 1
    while os.path.exists(dst): n += 1; dst = f'{base}-{n}'
    shutil.copyfile(db_path, dst)
    return dst


def is_legacy(db_path):
    """a DB created by work/db.py: has tables but no alembic_version"""
    if not os.path.exists(db_path): return False
    con = sqlite3.connect(db_path)
    try: return _has_table(con, 'matches') and not _has_table(con, 'alembic_version')
    finally: con.close()


def adopt_legacy(db_path, log=print):
    """back up, add the ALTER-era columns a very old file may miss, stamp as the baseline revision"""
    dst = backup(db_path); log(f'[db] pre-ORM database: backup at {dst}')
    con = sqlite3.connect(db_path)
    try:
        for tbl, col, typ in LEGACY_COLUMNS:
            if col not in [r[1] for r in con.execute(f'PRAGMA table_info({tbl})')]:
                con.execute(f'ALTER TABLE {tbl} ADD COLUMN {col} {typ}'); log(f'[db] added {tbl}.{col}')
        con.commit()
    finally:
        con.close()
    command.stamp(alembic_config(db_path), BASELINE)


class SchemaOutdated(RuntimeError):
    pass


def require_current(db_path):
    """raise SchemaOutdated when the file's revision is not the code's head (or the file is pre-ORM)"""
    cur, head = current_revision(db_path), head_revision()
    if cur != head:
        raise SchemaOutdated(f'{db_path}: schema revision {cur or "(pre-ORM)"} but this code needs {head}. '
                             f'Stop the backend and run:  uv run python -m app.db upgrade --db "{db_path}"  (a backup is taken first)')
    return head


def upgrade(db_path, log=print):
    """create or migrate the file to the newest revision; returns (revision before, revision after)"""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)) or '.', exist_ok=True)
    if is_legacy(db_path): adopt_legacy(db_path, log)
    before = current_revision(db_path); head = head_revision()
    if before != head:
        command.upgrade(alembic_config(db_path), 'head')
        log(f'[db] {os.path.basename(db_path)}: schema {before or "(new)"} -> {head}')
    return before, head
