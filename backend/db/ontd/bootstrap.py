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

The guard is not just "has it ever run". seed.py DROPs input_params on
every start, so the stop catalog can change under a projection that the
guard would otherwise consider done — leaving ontd.stop_mappings and
route_summaries.stop_ids pointing at stop ids the new catalog no longer
has (the 2026-08 pipeline restructure replaced 21 such objects). That
drift is detected here and repaired by re-running step 3 alone: the
timetable and the curated composition catalog do not depend on the stop
catalog, so there is no reason to re-download or re-route them.

Drift detection is one-directional by design: it catches mappings left
pointing at removed stops, which is the harmful case (dead ids reaching
the gallery). A catalog that only *adds* stops leaves previously
unmatched ONTD stops unmatched until the next --force; they keep their
raw ids meanwhile, which is the documented fallback.

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


def already_loaded() -> bool:
    """True when a previous bootstrap left route_summaries populated.

    Checked against the projection rather than the raw tables: it is the
    last thing written, so a partially-completed run still looks unloaded
    and gets retried.
    """
    try:
        conn = connect()
    except SystemExit:
        raise
    except Exception as e:
        print(f"[ontd] cannot reach the database ({type(e).__name__}: {e})")
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('ontd.route_summaries')")
            if cur.fetchone()[0] is None:
                return False
            cur.execute("SELECT count(*) FROM ontd.route_summaries")
            return cur.fetchone()[0] > 0
    finally:
        conn.close()


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
    unrefreshed projection. Returns 0 when nothing is stale, and also when
    the tables do not exist yet (a first run has nothing to be stale)."""
    try:
        conn = connect()
    except SystemExit:
        raise
    except Exception as e:
        print(f"[ontd] cannot reach the database ({type(e).__name__}: {e})")
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('ontd.stop_mappings')")
            if cur.fetchone()[0] is None:
                return 0
            cur.execute("""
                SELECT count(*) FROM ontd.stop_mappings m
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM input_params.stop_infrastructures s
                    JOIN scenario.scenarios sc
                      ON sc.stop_infrastructures_version = s.stop_infra_version
                    WHERE sc.is_current_base AND s.stop_id = m.tn_stop_id
                )
                """)
            return cur.fetchone()[0]
    except Exception as e:
        # Never fatal: a drift check that cannot run must not stop a
        # bootstrap that would otherwise proceed.
        print(f"[ontd] stop-mapping drift check skipped ({type(e).__name__}: {e})")
        return 0
    finally:
        conn.close()


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

    steps = STEPS
    if not (args.force or mode == "force") and already_loaded():
        stale = stale_stop_mappings()
        if not stale:
            print("[ontd] already loaded — skipping (ONTD_BOOTSTRAP=force to reload).")
            return 0
        print(
            f"[ontd] {stale} stop mapping(s) target stop ids the current "
            "catalog no longer has — the catalog was reseeded under this "
            "projection. Re-running the projection only; the timetable and "
            "composition catalog do not depend on the stop catalog."
        )
        steps = [step for step in STEPS if step[0] == "projection + geometry"]

    for label, argv in steps:
        if not run_step(label, argv):
            print(
                "[ontd] bootstrap incomplete. Existing-route context will be "
                "missing or partial; everything else is unaffected. Re-run "
                "with: python db/ontd/bootstrap.py --force"
            )
            return 1 if args.strict else 0

    print("[ontd] bootstrap complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
