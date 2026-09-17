"""Schema revisions of a DB file (Alembic under app/db/migrations).

A missing file is created at the current revision. An existing file is migrated only on request:
`uv run python -m app.db upgrade [--db PATH]` (stop the backend first); it copies the file to
<db>.bak-<date>-<old revision> before applying anything, and a migration runs inside one transaction.
The store refuses an outdated file (`require_current`) instead of migrating it.
Files from before the SQLAlchemy move (no alembic_version table) are not handled any more: the one-off
migration for those lived in commit 4cba342 (branch sqlalchemy-migration, 2026-09-17).
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


def alembic_config(db_path):
    cfg = Config()
    cfg.set_main_option('script_location', MIGRATIONS)
    cfg.set_main_option('db_path', os.path.abspath(db_path))
    return cfg


def current_revision(db_path):
    """revision stamped in the file; None for an empty file or one without alembic_version"""
    if not os.path.exists(db_path): return None
    engine = create_engine(db_url(db_path), poolclass=NullPool)
    with engine.connect() as con:
        return MigrationContext.configure(con).get_current_revision()


def head_revision():
    cfg = Config(); cfg.set_main_option('script_location', MIGRATIONS)
    return ScriptDirectory.from_config(cfg).get_current_head()


def backup(db_path, tag):
    """checkpoint the WAL and copy the file: <db>.bak-YYYY-MM-DD-<tag> (a counter is added if that exists)"""
    con = sqlite3.connect(db_path)
    try: con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally: con.close()
    base = f'{db_path}.bak-{time.strftime("%Y-%m-%d")}-{tag}'; dst = base; n = 1
    while os.path.exists(dst): n += 1; dst = f'{base}-{n}'
    shutil.copyfile(db_path, dst)
    return dst


class SchemaOutdated(RuntimeError):
    pass


def require_current(db_path):
    """raise SchemaOutdated when the file's revision is not the code's head"""
    cur, head = current_revision(db_path), head_revision()
    if cur != head:
        raise SchemaOutdated(f'{db_path}: schema revision {cur or "(none)"} but this code needs {head}. '
                             f'Stop the backend and run:  uv run python -m app.db upgrade --db "{db_path}"  (a backup is taken first)')
    return head


def upgrade(db_path, log=print):
    """create the file, or migrate it to the newest revision (after a backup); returns (revision before, revision after)"""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)) or '.', exist_ok=True)
    before = current_revision(db_path); head = head_revision()
    if before != head:
        if os.path.exists(db_path) and os.path.getsize(db_path):
            log(f'[db] backup at {backup(db_path, before or "unversioned")}')
        command.upgrade(alembic_config(db_path), 'head')
        log(f'[db] {os.path.basename(db_path)}: schema {before or "(new)"} -> {head}')
    return before, head
