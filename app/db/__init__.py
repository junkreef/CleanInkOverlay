"""The database layer: SQLAlchemy models (models.py), engine/session (engine.py), reusable queries (queries.py),
schema migrations with Alembic (migrate.py + migrations/). app.store.Store is the only user: it creates a
missing file at the current schema and refuses an outdated one; migrating an existing data/splatoon.db
(with a backup) is an explicit step:

    python -m app.db init|upgrade|current|stats|matches [--db PATH]
"""
from .engine import DEFAULT_DB, make_engine, make_session_factory
from .migrate import SchemaOutdated, upgrade, require_current, current_revision, head_revision, known_revisions
from .models import Base, Event, Match, MatchPlayer, Medal, Timeline, Weapon

__all__ = ['DEFAULT_DB', 'make_engine', 'make_session_factory', 'SchemaOutdated', 'upgrade', 'require_current',
           'current_revision', 'head_revision', 'known_revisions', 'Base', 'Event', 'Match', 'MatchPlayer', 'Medal', 'Timeline', 'Weapon']
