"""The database layer: SQLAlchemy models (models.py), engine/session (engine.py), reusable queries (queries.py),
schema migrations with Alembic (migrate.py + migrations/). app.store.Store is the only user; it calls
`upgrade()` when it opens a file, so an old data/splatoon.db is migrated in place (with a backup) on first start.

    python -m app.db init|upgrade|current|stats|matches [--db PATH]
"""
from .engine import DEFAULT_DB, make_engine, make_session_factory
from .migrate import upgrade, current_revision, head_revision
from .models import Base, Event, Match, MatchPlayer, Medal, Timeline, Weapon

__all__ = ['DEFAULT_DB', 'make_engine', 'make_session_factory', 'upgrade', 'current_revision', 'head_revision',
           'Base', 'Event', 'Match', 'MatchPlayer', 'Medal', 'Timeline', 'Weapon']
