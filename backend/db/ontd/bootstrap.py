"""
Load the ONTD once, at database bootstrap.

The ONTD is reference data seeded alongside everything else, not a
manual chore: a fresh database should come up with existing night trains
already in it. This wraps the three loaders in the one order that works
and, crucially, in a guard — so a container restart does not re-download
the workbook and re-route 205 routes every time.

Order matters and is not interchangeable:
  1. loader.py --no-geometry   creates the ontd schema and loads the
     timetable. Geometry is skipped here because step 3 does it once,
     after composition assignments exist; routing twice would double the
     slowest part of the run.
  2. composition_loader.py     curated catalog; requires ontd.routes to
     exist, and refuses to overwrite curated tables that already hold
     data.
  3. projection.py             route_summaries + route_legs, including
     the routed geometry.

Started in the BACKGROUND by the API container's entrypoint, so nothing
here delays the API coming up; the gallery gains existing routes when it
finishes. Routing inside step 3 is itself concurrent
(ONTD_ROUTING_WORKERS), which is what keeps that under a minute.

Failure is never fatal. The API serves proposals perfectly well without
existing-route context, so a Drive outage or a router that is not ready
must not keep the container from starting — this exits 0 and says what
went wrong, unless --strict is passed.

The guard is not just "has it ever run". Two kinds of drift are detected
and repaired by re-running step 3 alone — the timetable and the curated
composition catalog do not depend on either, so nothing is re-downloaded
or re-loaded:

  * STALE STOP MAPPINGS. seed.py DROPs input_params on every start, so
    the stop catalog can change under a projection the guard would
    otherwise consider done — leaving ontd.stop_mappings and
    route_summaries.stop_ids pointing at stop ids the new catalog no
    longer has (the 2026-08 pipeline restructure replaced 21 such
    objects). Detection is one-directional by design: it catches
    mappings left pointing at removed stops, which is the harmful case
    (dead ids reaching the gallery). A catalog that only *adds* stops
    leaves previously unmatched ONTD stops unmatched until the next
    --force; they keep their raw ids meanwhile, the documented fallback.
  * UNROUTED PROJECTION. Step 1 writes route_summaries with straight-line
    placeholder geometry (geometry_routed = FALSE on every row) that step
    3 is meant to replace. If step 3 never ran or the router was down at
    the time, the placeholder is what the gallery map shows — every
    existing train as a dashed straight line. A projection with no routed
    row is therefore re-run at the next start; it costs one routing pass
    and nothing else, and simply repeats if the router is still down.

Step 2 is skipped, not failed, when the curated tables already hold data:
composition_loader.py refuses to overwrite hand-maintained tables (its
own guard, for manual runs), and a populated catalog is the bootstrap's
desired end state, not an error. Before this rule (2026-09-06) every
restart of a persisted-volume stack failed at step 2 and never reached
the routing step — which is how the whole gallery came to be dashed.

ONTD_BOOTSTRAP controls it (env, so a deployment can decide without a
code change):
    auto   (default)  load when ontd.route_summaries is empty, and
                      re-project when the stop catalog has moved on
    force             load even if already populated
    off               skip entirely

Usage:
    python db/ontd/bootstrap.py            # honours ONTD_BOOTSTRAP
    python db/ontd/bootstrap.py --force
    python db/ontd/bootstrap.py --strict   # non-zero exit on failure
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from connection import connect

HERE = Path(__file__).resolve().parent

STEPS = (
    ("timetable", ["loader.py", "--no-geometry"]),
    ("composition catalog", ["composition_loader.py"]),
    ("projection + geometry", ["projection.py"]),
)


def _guard_query(run, default):
    """Run one guard check `run(cur)` against the database, returning
    `default` when the database is unreachable or the tables do not exist
    yet (a first run has nothing to probe). Every check below goes
    through here, so a database hiccup can never stop a bootstrap that
    would otherwise proceed — the worst case is repeating work."""
    try:
        conn = connect()
    except SystemExit:
        raise
    except Exception as e:
        print(f"[ontd] cannot reach the database ({type(e).__name__}: {e})")
        return default
    try:
        with conn.cursor() as cur:
            return run(cur)
    except Exception as e:
        print(f"[ontd] guard check skipped ({type(e).__name__}: {e})")
        return default
    finally:
        conn.close()


def _scalar(query: str):
    def run(cur):
        cur.execute(query)
        return cur.fetchone()[0]

    return run


def already_loaded() -> bool:
    """True when a previous bootstrap left route_summaries populated.

    Checked against the projection rather than the raw tables: it is the
    last thing written, so a partially-completed run still looks unloaded
    and gets retried.
    """
    return bool(_guard_query(_scalar("SELECT count(*) FROM ontd.route_summaries"), 0))


def unrouted_projection() -> bool:
    """True when route_summaries has rows but none carries routed geometry
    — the straight-line placeholder step 1 leaves for step 3 to replace
    (module docstring, UNROUTED PROJECTION)."""
    return not _guard_query(
        _scalar(
            "SELECT coalesce(bool_or(geometry_routed), false) FROM ontd.route_summaries"
        ),
        True,
    )


def curated_catalog_loaded() -> bool:
    """True when the composition catalog is already in the curated tables,
    which makes step 2 a no-op — see populated_curated_tables()."""
    from composition_loader import populated_curated_tables

    return bool(_guard_query(populated_curated_tables, []))


def plan_steps(
    force: bool,
    loaded: bool,
    stale_mappings: int,
    unrouted: bool,
    catalog_loaded: bool,
) -> tuple[list[tuple[str, list[str]]], str]:
    """Which steps to run, from the guard facts — pure, so the decision
    table is unit-testable without a database (tests/test_81).

    Returns (steps, reason); an empty step list means nothing to do.
    """
    projection_only = [step for step in STEPS if step[0] == "projection + geometry"]
    if force:
        steps = list(STEPS)
        reason = "forced reload"
    elif not loaded:
        steps = list(STEPS)
        reason = "route_summaries empty"
    elif stale_mappings:
        steps = projection_only
        reason = (
            f"{stale_mappings} stop mapping(s) target stop ids the current "
            "catalog no longer has — the catalog was reseeded under this "
            "projection"
        )
    elif unrouted:
        steps = projection_only
        reason = (
            "route_summaries holds no routed geometry — the projection is "
            "the straight-line placeholder"
        )
    else:
        return [], "already loaded"

    if catalog_loaded:
        steps = [step for step in steps if step[0] != "composition catalog"]
    return steps, reason


def run_step(label: str, argv: list[str]) -> bool:
    print(f"[ontd] {label} ...")
    result = subprocess.run([sys.executable, str(HERE / argv[0]), *argv[1:]])
    if result.returncode != 0:
        print(f"[ontd] {label} FAILED (exit {result.returncode})")
        return False
    return True


def stale_stop_mappings() -> int:
    """Mapping rows targeting stop ids absent from the base scenario's
    pinned catalog snapshot — the signature of a reseeded catalog under an
    unrefreshed projection. 0 when nothing is stale."""
    return _guard_query(
        _scalar(
            """
            SELECT count(*) FROM ontd.stop_mappings m
            WHERE NOT EXISTS (
                SELECT 1
                FROM input_params.stop_infrastructures s
                JOIN scenario.scenarios sc
                  ON sc.stop_infrastructures_version = s.stop_infra_version
                WHERE sc.is_current_base AND s.stop_id = m.tn_stop_id
            )
            """
        ),
        0,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force", action="store_true", help="Reload even if already populated"
    )
    parser.add_argument(
        "--strict", action="store_true", help="Exit non-zero if any step fails"
    )
    args = parser.parse_args()

    mode = os.environ.get("ONTD_BOOTSTRAP", "auto").strip().lower()
    if mode == "off" and not args.force:
        print("[ontd] ONTD_BOOTSTRAP=off — skipping.")
        return 0
    if mode not in ("auto", "force", "off"):
        print(f"[ontd] ONTD_BOOTSTRAP='{mode}' not recognised — treating as 'auto'.")
        mode = "auto"

    force = args.force or mode == "force"
    loaded = already_loaded()
    steps, reason = plan_steps(
        force=force,
        loaded=loaded,
        stale_mappings=stale_stop_mappings() if loaded and not force else 0,
        unrouted=unrouted_projection() if loaded and not force else False,
        catalog_loaded=curated_catalog_loaded(),
    )
    if not steps:
        print("[ontd] already loaded — skipping (ONTD_BOOTSTRAP=force to reload).")
        return 0
    skipped = [label for label, _ in STEPS if (label, _) not in steps]
    print(f"[ontd] {reason} — running: {', '.join(label for label, _ in steps)}")
    if skipped:
        print(f"[ontd] skipping (already loaded, unaffected): {', '.join(skipped)}")

    for label, argv in steps:
        if not run_step(label, argv):
            print(
                "[ontd] bootstrap incomplete. Existing-route context will be "
                "missing or partial; everything else is unaffected. The "
                "next container start retries the projection; to retry now: "
                "python db/ontd/bootstrap.py"
            )
            return 1 if args.strict else 0

    print("[ontd] bootstrap complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
