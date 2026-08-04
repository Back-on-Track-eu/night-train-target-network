"""
refresh_proposals.py
=====================
Batch job (PROPOSALS_DESIGN.md §4.2): recompute + overwrite in place every
published proposal whose stored route_builder_version/calc_version has
fallen behind the running code, or whose scenario_id is no longer the
current base scenario. Run manually after every version bump or base-
scenario move; safe to run speculatively too (a no-op when nothing is
outdated) — e.g. from a periodic cron/CI job as a correctness backstop
alongside the on-load fallback (api/proposals.py).

Idempotent and resumable: adapters/proposal/repository.py's
list_outdated() re-derives the work queue fresh on every run from current
DB state, so a proposal drops out the moment it's current — an
interrupted run is simply resumed by rerunning, no bookkeeping needed.

Direct in-process, not HTTP: a refresh is a system action with no owner
and no auth concept (ProposalRepository.refresh_proposal() deliberately
has no ownership check), the same reason db/dev/seed.py's example-
proposal seed talks to the repository directly rather than through the
API. Uses api.helpers.dependencies.init() — the same singleton wiring
main.py uses at Flask startup — so this script needs a reachable Postgres
and a running OpenRailRouting, exactly like the API process does.

Env vars: unlike main.py (which runs inside a container where Docker
Compose's env_file already injects POSTGRES_*, and the loader/router
singletons default to service-name hosts), this script is meant to also
run standalone from the host — same situation tests/conftest.py's own
DB_CONFIG is in. run() below sets the same host-side defaults conftest.py
uses (POSTGRES_HOST=localhost, etc., via setdefault() — never overrides
a value a container already injected). Deliberately does NOT load
backend/docker/.env: that file's POSTGRES_HOST=postgres and
OPENRAILROUTING_URL=http://openrailrouting:8989 are Docker Compose
network hostnames, meaningless (and actively wrong) from the host;
models/route/routing/rail_router.py's RailRouter already falls back to
http://localhost:8989 on its own when OPENRAILROUTING_URL is unset, so
nothing extra is needed there as long as this script leaves it alone.

Concurrency (WP14 context — see docs/PROPOSALS_DESIGN.md §10): only the
live-routing compute step is parallelized across --concurrency worker
threads, each with its own DBDataLoader (cheap — one psycopg2 connection,
no heavy precompute) sharing the one process-wide RailRouter, which is
explicitly built for concurrent use (pooled requests.Session — see
api/helpers/dependencies.py). DB writes (refresh_proposal()) stay
sequential on the main thread against the single shared
ProposalRepository connection, which is NOT thread-safe — writes were
never the bottleneck (routing calls are), and serializing them here also
means only one FOR UPDATE lock is ever held at a time.

Compute-cache flush: §4.2 calls for flushing the compute cache first on
every version bump / base move so stale cached results can't leak back
into a fresh /calc — ProposalRepository.flush_compute_cache() (called
below before processing starts). WP13 (the cache's actual read/write
logic) hasn't landed yet, so proposals.compute_cache_pointer/_result are
always empty today — the flush is a correct no-op now and needs no
revisiting once WP13 ships.

Usage:
    uv run --extra dev python -m scripts.refresh_proposals [--dry-run] [--limit N] [--concurrency N]
"""

from __future__ import annotations

import argparse
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from adapters.data_loader_from_db import DBDataLoader
from adapters.proposal.repository import outdated_trigger
from api.helpers import dependencies
from api.helpers.proposal_compute import compute_proposal

logger = logging.getLogger(__name__)


def _compute_one(row: dict) -> tuple[dict, dict]:
    """Runs on a worker thread — its own DBDataLoader, the shared
    RailRouter (see module docstring). Returns (computed, trigger); the
    DB write happens back on the main thread."""
    trigger = outdated_trigger(row)
    # Can't happen in practice — list_outdated() already filtered to
    # exactly the rows outdated_trigger() agrees are outdated — but a
    # defensive check here is cheap and turns a silent no-op into a loud
    # bug report if the two ever disagree.
    assert trigger is not None, (
        f"list_outdated() returned proposal_id={row['proposal_id']} but "
        "outdated_trigger() found nothing outdated about it."
    )

    thread_loader = DBDataLoader()
    try:
        refresh_request = dict(row["compute_request"])
        # Re-resolve fresh against the current base rather than replaying
        # the stored (possibly stale) scenario_id — a refresh always lands
        # on whatever base is current NOW, regardless of which trigger
        # fired (see api/proposals.py's on-load fallback for the same
        # rule applied on the read path).
        refresh_request["scenario_id"] = None
        computed = compute_proposal(
            refresh_request,
            loader=thread_loader,
            router=dependencies.get_rail_router(),
        )
    finally:
        thread_loader.close()

    return computed, trigger


def run(
    dry_run: bool = False,
    limit: int | None = None,
    concurrency: int = 1,
) -> int:
    """Returns the number of proposals that failed to refresh (0 = fully
    clean run, including the trivial case of nothing being outdated)."""
    # Host-side defaults matching tests/conftest.py's DB_CONFIG exactly —
    # setdefault() is a no-op wherever a container has already injected
    # the compose-network values (POSTGRES_HOST=postgres etc.), so this
    # is safe in both contexts. See module docstring for why this is
    # deliberately NOT a load_dotenv() against backend/docker/.env.
    os.environ.setdefault("POSTGRES_HOST", "localhost")
    os.environ.setdefault("POSTGRES_PORT", "5432")
    os.environ.setdefault("POSTGRES_DB", "target_network_test_db")
    os.environ.setdefault("POSTGRES_USER", "bot_admin")
    os.environ.setdefault("POSTGRES_PASSWORD", "devpassword")

    dependencies.init()
    repo = dependencies.get_proposal_repository()

    outdated = repo.list_outdated(limit=limit)
    logger.info("%d proposal(s) outdated.", len(outdated))
    if not outdated:
        return 0

    if dry_run:
        for row in outdated:
            trigger = outdated_trigger(row)
            logger.info(
                "[dry-run] would refresh proposal_id=%s (%s: %s -> %s)",
                row["proposal_id"],
                trigger["trigger"],
                trigger["from"],
                trigger["to"],
            )
        return 0

    repo.flush_compute_cache()

    failures = 0
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        future_to_row = {pool.submit(_compute_one, row): row for row in outdated}
        for future in as_completed(future_to_row):
            row = future_to_row[future]
            try:
                computed, trigger = future.result()
                repo.refresh_proposal(row["proposal_id"], computed, detail=trigger)
                logger.info(
                    "refreshed proposal_id=%s (%s: %s -> %s)",
                    row["proposal_id"],
                    trigger["trigger"],
                    trigger["from"],
                    trigger["to"],
                )
            except Exception:
                failures += 1
                logger.exception(
                    "refresh failed for proposal_id=%s", row["proposal_id"]
                )

    logger.info(
        "Refresh complete: %d ok, %d failed.", len(outdated) - failures, failures
    )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="List what would be refreshed only."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Cap the number of proposals processed."
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Worker threads for the live-routing compute step (see module docstring).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s"
    )

    failures = run(dry_run=args.dry_run, limit=args.limit, concurrency=args.concurrency)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
