"""
purge_request_log.py
====================
Delete admin.request_log rows older than the retention window. Belongs on
a cron; the table is otherwise unbounded (roughly 200 bytes a row, one row
per served request).

Retention is a policy, not a database constraint, which is why it lives in
a script rather than a trigger or a partition rule: the number is
REQUEST_LOG_RETENTION_DAYS (api/config.py, overridable per deployment),
and the same table can legitimately be kept for 30 days on staging and 90
in production.

Host-runnable like scripts/refresh_proposals.py — POSTGRES_* default to
localhost via dev_env, never overriding container-injected values.

Predict-before-run: --dry-run reports what would go and what would remain,
so a retention change is checked against real counts before it deletes
anything.

Usage:
  uv run python scripts/purge_request_log.py --dry-run
  uv run python scripts/purge_request_log.py
  uv run python scripts/purge_request_log.py --days 30
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dev_env  # noqa: E402

dev_env.resolve_env()

from adapters.request_log_repository import RequestLogRepository  # noqa: E402
from api import config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger("purge_request_log")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=config.REQUEST_LOG_RETENTION_DAYS,
        help="retention window (default: REQUEST_LOG_RETENTION_DAYS)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the counts and delete nothing",
    )
    args = parser.parse_args()

    if args.days < 1:
        logger.error("Retention must be at least one day; got %d.", args.days)
        return 1

    repo = RequestLogRepository()
    try:
        before = repo.count()
        logger.info("admin.request_log holds %d row(s).", before)

        if args.dry_run:
            # Counted the same way purge_older_than() deletes, so the dry
            # run cannot disagree with the real one about the boundary.
            with repo._conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM admin.request_log "
                    "WHERE occurred_at < now() - make_interval(days => %s)",
                    (args.days,),
                )
                stale = int(cur.fetchone()[0])
            logger.info(
                "Dry run: %d row(s) older than %d day(s) would be deleted, "
                "%d would remain.",
                stale,
                args.days,
                before - stale,
            )
            return 0

        deleted = repo.purge_older_than(args.days)
        logger.info(
            "Deleted %d row(s) older than %d day(s); %d remain.",
            deleted,
            args.days,
            before - deleted,
        )
        return 0
    finally:
        repo.close()


if __name__ == "__main__":
    raise SystemExit(main())
