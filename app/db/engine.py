"""Engine / session factory for the SQLite file. Every connection gets foreign keys on and WAL journaling,
so the recorder thread and the web workers can read and write the same file concurrently."""
import os
from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import sessionmaker

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DEFAULT_DB = os.path.join(ROOT, 'data', 'splatoon.db')


def db_url(path=DEFAULT_DB):
    return URL.create('sqlite', database=os.path.abspath(path))


def make_engine(path=DEFAULT_DB, **kw):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    engine = create_engine(db_url(path), connect_args={'check_same_thread': False, 'timeout': 30}, **kw)

    @event.listens_for(engine, 'connect')
    def _pragmas(dbapi_con, _record):
        cur = dbapi_con.cursor()
        cur.execute('PRAGMA foreign_keys = ON')
        cur.execute('PRAGMA journal_mode = WAL')
        cur.close()
    return engine


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
