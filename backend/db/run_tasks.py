"""
run_tasks.py — run pending data tasks (batch operations) on a database.
=======================================================================

The second half of the deploy's database pipeline, next to ``migrate.py``:

  * ``migrate.py`` changes the SCHEMA. SQL files, one transaction each,
    fast, and the api must not start before they are through.
  * ``run_tasks.py`` changes the DATA in bulk. Python files in
    ``db/tasks/``, each a self-contained batch operation — backfilling a
    new derived table, re-projecting every proposal after a route-builder
    bump, rewriting stored requests after a model change. They may take
    minutes or hours and may need the routing engines, so they run in a
    one-shot container AFTER the migrations and BESIDE the starting api
    (``deploy/coolify/app.docker-compose.yml`` service ``data-tasks``;
    ``docker/entrypoint.sh`` backgrounds them on a dev stack). Code that
    depends on a task's result has to cope with the window before it has
    run — the way ``map_lines`` falls back to deriving corridors while
    ``proposal_corridors`` is incomplete.

Which tasks a database has run is recorded in ``admin.data_task_runs``
(one row per attempt, with outcome and a one-line summary), created by
this script on first contact like ``migrate.py`` does its own table. A
task is PENDING until one of its runs ended ``done``; a ``failed`` run
leaves it pending, so the next deploy retries it. Tasks run in filename
order, each only after every schema migration has been applied — a
pending migration stops this script before any task starts.

A task file is a module exposing::

    DESCRIPTION = "one line, what this does"

    def run(ctx, dry_run: bool) -> str:
        ...  # returns the one-line summary that is recorded

``ctx`` is a TaskContext: ``ctx.conn`` (a psycopg2 connection the runner
commits after a successful run and rolls back on an exception),
``ctx.repo`` (the ProposalRepository, built on first use) and
``ctx.log``. A task that needs the loader or the routing engines calls
``api.helpers.dependencies.init()`` itself, exactly as
``scripts/refresh_proposals.py`` does; the ``data-tasks`` service carries
the same ``OPENRAILROUTING_URL_*`` variables as the api for that. Tasks
must be idempotent and resumable: derive the work queue from the current
database state and skip what is already done, so an interrupted run is
simply run again. ``dry_run`` means "report what you would do, change
nothing".

Usage:
    python db/run_tasks.py                # run pending tasks, in order
    python db/run_tasks.py --list         # every task with its status
    python db/run_tasks.py --dry-run      # run pending tasks in dry-run mode, record nothing
    python db/run_tasks.py --check        # exit 2 if tasks are pending
    python db/run_tasks.py --run FILE     # run ONE task even if it is done (re-run)
    python db/run_tasks.py --baseline     # record every pending task as done WITHOUT running it

``--baseline`` is for a database that cannot need a task's work — a fresh
seed, whose rows every write path has produced correctly from the start —
and is used exactly once per such database, like ``migrate.py --baseline``.

Connection comes from the same environment variables ``migrate.py`` uses:
POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import psycopg2

# Sibling script, importable because `python db/run_tasks.py` puts db/ first
# on sys.path. Also lets the api image's /app layout import it the same way.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import migrate  # noqa: E402

# Project root (backend/), for `adapters.*` / `api.*` imports inside tasks.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TASKS_DIR = Path(__file__).parent / "tasks"

TRACKING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS admin.data_task_runs (
    run_id      BIGSERIAL PRIMARY KEY,
    filename    TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status      TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed', 'baselined')),
    summary     TEXT
);
CREATE INDEX IF NOT EXISTS idx_data_task_runs_filename
    ON admin.data_task_runs (filename, run_id DESC);
"""

logger = logging.getLogger("run_tasks")


@dataclass
class TaskContext:
    """What a task gets handed — see the module docstring."""

    conn: psycopg2.extensions.connection
    log: logging.Logger
    _repo: object = field(default=None, repr=False)

    @property
    def repo(self):
        """The ProposalRepository, on the process-wide pool built from the
        same POSTGRES_* variables. Lazy: a pure-SQL task never pays for
        it, and importing adapters only when needed keeps this script
        usable without the api's dependency tree on the path."""
        if self._repo is None:
            from adapters.proposal.repository import ProposalRepository

            self._repo = ProposalRepository()
        return self._repo


def _ensure_tracking_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(TRACKING_TABLE_SQL)
    conn.commit()


def _task_files() -> list[str]:
    return sorted(p.name for p in TASKS_DIR.glob("*.py") if not p.name.startswith("_"))


def _completed(conn) -> set[str]:
    """Filenames with at least one run that ended done or baselined."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT filename FROM admin.data_task_runs "
            "WHERE status IN ('done', 'baselined')"
        )
        return {row[0] for row in cur.fetchall()}


def _last_runs(conn) -> dict[str, tuple]:
    """filename -> (status, finished_at, summary) of its most recent run."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ON (filename) filename, status, finished_at, summary "
            "FROM admin.data_task_runs ORDER BY filename, run_id DESC"
        )
        return {row[0]: row[1:] for row in cur.fetchall()}


def _pending(conn) -> list[str]:
    completed = _completed(conn)
    return [f for f in _task_files() if f not in completed]


def _load(filename: str) -> ModuleType:
    """Import a task file by path — the date-prefixed names are not valid
    module names, so importlib's spec API rather than `import`."""
    path = TASKS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"data_task_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "run", None)):
        sys.exit(f"run_tasks.py: {filename} defines no run(ctx, dry_run) function.")
    return module


def _record_start(conn, filename: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO admin.data_task_runs (filename, status) "
            "VALUES (%s, 'running') RETURNING run_id",
            (filename,),
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def _record_end(conn, run_id: int, status: str, summary: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE admin.data_task_runs SET status = %s, finished_at = now(), "
            "summary = %s WHERE run_id = %s",
            (status, summary[:2000], run_id),
        )
    conn.commit()


def _run_one(tracking_conn, filename: str, dry_run: bool) -> bool:
    """Run one task on its own connection, record the outcome on the
    tracking connection. Returns True on success. The two connections
    are deliberately separate: a task that fails mid-transaction must
    not take its own failure record down with it."""
    module = _load(filename)
    description = getattr(module, "DESCRIPTION", "").strip()
    print(f"run_tasks.py: {'[dry-run] ' if dry_run else ''}{filename} — {description}")

    run_id = None if dry_run else _record_start(tracking_conn, filename)
    task_conn = migrate._connect()
    started = time.monotonic()
    try:
        ctx = TaskContext(conn=task_conn, log=logging.getLogger(Path(filename).stem))
        summary = module.run(ctx, dry_run=dry_run) or ""
        task_conn.commit()
    except Exception as exc:  # noqa: BLE001 — every failure is recorded, then re-raised by exit
        task_conn.rollback()
        elapsed = time.monotonic() - started
        logger.exception("task %s failed after %.1f s", filename, elapsed)
        if run_id is not None:
            _record_end(tracking_conn, run_id, "failed", f"{type(exc).__name__}: {exc}")
        return False
    finally:
        task_conn.close()
    elapsed = time.monotonic() - started
    print(f"  {summary} ({elapsed:.1f} s)")
    if run_id is not None:
        _record_end(tracking_conn, run_id, "done", summary)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="every task and its status")
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="run pending tasks in dry-run mode, record nothing",
    )
    mode.add_argument(
        "--check", action="store_true", help="exit 2 if tasks are pending"
    )
    mode.add_argument(
        "--run", metavar="FILE", help="run this one task now, even if already done"
    )
    mode.add_argument(
        "--baseline",
        action="store_true",
        help="record every pending task as done WITHOUT running it",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s"
    )

    conn = migrate._connect()
    try:
        migrate._ensure_tracking_table(conn)
        _ensure_tracking_table(conn)

        # Tasks assume the schema they were written against.
        pending_migrations = migrate._pending(conn)
        if pending_migrations:
            sys.exit(
                "run_tasks.py: schema migrations are pending — run db/migrate.py first: "
                + ", ".join(pending_migrations)
            )

        if args.list:
            last = _last_runs(conn)
            for f in _task_files():
                status, finished_at, summary = last.get(f, ("pending", None, None))
                when = f" {finished_at:%Y-%m-%d %H:%M}" if finished_at else ""
                print(
                    f"  {status:<9}{when}  {f}" + (f" — {summary}" if summary else "")
                )
            return

        if args.run:
            if args.run not in _task_files():
                sys.exit(f"run_tasks.py: no task file {args.run} in {TASKS_DIR}")
            ok = _run_one(conn, args.run, dry_run=False)
            sys.exit(0 if ok else 1)

        pending = _pending(conn)
        if args.check:
            if pending:
                print(
                    f"run_tasks.py: {len(pending)} pending task(s): "
                    + ", ".join(pending)
                )
                sys.exit(2)
            print("run_tasks.py: no pending tasks.")
            return

        if args.baseline:
            if not pending:
                print("run_tasks.py: nothing to baseline.")
                return
            with conn.cursor() as cur:
                for f in pending:
                    cur.execute(
                        "INSERT INTO admin.data_task_runs (filename, status, finished_at, summary) "
                        "VALUES (%s, 'baselined', now(), 'recorded by --baseline, not run')",
                        (f,),
                    )
            conn.commit()
            print(
                f"run_tasks.py: baselined {len(pending)} task(s) (recorded, NOT run):"
            )
            for f in pending:
                print(f"  {f}")
            return

        if not pending:
            print("run_tasks.py: no pending tasks.")
            return
        failures = 0
        for f in pending:
            if not _run_one(conn, f, dry_run=args.dry_run):
                failures += 1
                # Later tasks may build on this one's result; stop here and
                # let the next deploy retry from it, like migrate.py does.
                print(f"run_tasks.py: stopping after the failure of {f}.")
                break
        done = len(pending) - failures
        print(
            f"run_tasks.py: {'would run' if args.dry_run else 'ran'} {done} task(s)"
            + (f", {failures} failed" if failures else "")
            + "."
        )
        sys.exit(1 if failures else 0)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
