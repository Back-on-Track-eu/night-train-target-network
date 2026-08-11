"""
Database connection for the ontd scripts.

Named connection.py, not db.py: backend/db/ is a namespace package, and
while a regular module still wins the import, the two would be one
__init__.py away from colliding.

All environment resolution lives in backend/dev_env.py — the single
resolver for host-run tooling. This module used to carry its own .env
search order and its own connection defaults; those defaults had drifted
to the retired production names (night_train_db / nighttrain) while the
rest of the repo assumed target_network_test_db / bot_admin, so a script
run without a .env silently targeted a database nothing else used. One
resolver, one default set, no drift.

The historical trap this solves is documented on dev_env.resolve_env():
these scripts used to fall back to localhost defaults while DBDataLoader
(which projection.py needs) required all five POSTGRES_* explicitly —
so a partially-set environment let the loaders connect happily while
routing failed, surfacing only as every route silently falling back to
straight-line geometry. Resolving once and publishing to os.environ
keeps every consumer on the same connection.
"""

import sys
from pathlib import Path

import psycopg2

# Host-run entry points under db/ontd are executed as plain scripts
# (`uv run python db/ontd/loader.py`), so the backend root is not on
# sys.path by default.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dev_env import (  # noqa: E402  (path bootstrap must precede import)
    ENV_FILES,
    load_env_files,
    resolve_env,
    resolve_host,
    resolve_service_url,
)

__all__ = [
    "ENV_FILES",
    "load_env_files",
    "resolve_env",
    "resolve_host",
    "resolve_service_url",
    "connect",
]


def connect(autocommit: bool = False):
    """Open a connection to the configured database."""
    settings = resolve_env()
    try:
        conn = psycopg2.connect(
            host=settings["POSTGRES_HOST"],
            port=int(settings["POSTGRES_PORT"]),
            dbname=settings["POSTGRES_DB"],
            user=settings["POSTGRES_USER"],
            password=settings["POSTGRES_PASSWORD"],
        )
    except psycopg2.OperationalError as e:
        checked = "\n  ".join(str(p) for p in ENV_FILES)
        raise SystemExit(
            f"Could not connect to {settings['POSTGRES_USER']}@"
            f"{settings['POSTGRES_HOST']}:{settings['POSTGRES_PORT']}/"
            f"{settings['POSTGRES_DB']}.\n{e}"
            "Is the postgres container up, and is its port published?\n"
            "Configuration is read from:\n  " + checked
        ) from e
    conn.autocommit = autocommit
    return conn
