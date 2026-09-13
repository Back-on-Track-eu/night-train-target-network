"""
Unit tests for db/ontd/bootstrap.py's step selection (plan_steps) — the
decision table that turns the guard facts into a list of loader steps.
No DB, no Docker, no subprocess: every fact is passed in.

Two rules here have a history (2026-09-06, "every existing train dashed"):

  * a populated curated composition catalog SKIPS step 2 rather than
    running it — composition_loader.py exits non-zero on populated
    tables, and treating that as a bootstrap failure meant the routing
    step never ran on any persisted-volume stack;
  * a projection with no routed geometry RE-RUNS the routing step at the
    next start, instead of counting as "already loaded" forever.
"""

import sys
from pathlib import Path

import pytest

# db/ontd is a script directory (its modules import each other bare, the
# same way loader.py/projection.py run), not a package under backend/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "db" / "ontd"))

from bootstrap import STEPS, plan_steps  # noqa: E402

ALL = [label for label, _ in STEPS]
PROJECTION_ONLY = ["projection + geometry"]
WITHOUT_CATALOG = [label for label in ALL if label != "composition catalog"]


def labels(steps):
    return [label for label, _ in steps]


def test_step_order_is_the_documented_one():
    assert ALL == ["timetable", "composition catalog", "projection + geometry"]
    assert STEPS[0][1] == ["loader.py", "--no-geometry"]


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        # Fresh database: everything.
        (dict(loaded=False, stale_mappings=0, unrouted=False), ALL),
        # Fully loaded and routed: nothing.
        (dict(loaded=True, stale_mappings=0, unrouted=False), []),
        # Catalog reseeded under the projection: routing step only.
        (dict(loaded=True, stale_mappings=21, unrouted=False), PROJECTION_ONLY),
        # Straight-line placeholder left behind: routing step only.
        (dict(loaded=True, stale_mappings=0, unrouted=True), PROJECTION_ONLY),
        # Both drifts: still one routing pass.
        (dict(loaded=True, stale_mappings=3, unrouted=True), PROJECTION_ONLY),
    ],
)
def test_plan_without_curated_catalog(facts, expected):
    steps, _ = plan_steps(force=False, catalog_loaded=False, **facts)
    assert labels(steps) == expected


def test_populated_catalog_skips_step_two_on_fresh_load():
    """The regression: curated tables populated, route_summaries empty
    (or a forced reload). Step 2 must be skipped so step 3 still runs."""
    steps, _ = plan_steps(
        force=False, loaded=False, stale_mappings=0, unrouted=False, catalog_loaded=True
    )
    assert labels(steps) == WITHOUT_CATALOG

    steps, reason = plan_steps(
        force=True, loaded=True, stale_mappings=0, unrouted=False, catalog_loaded=True
    )
    assert labels(steps) == WITHOUT_CATALOG
    assert reason == "forced reload"


def test_force_runs_everything_on_an_empty_catalog():
    steps, _ = plan_steps(
        force=True, loaded=True, stale_mappings=0, unrouted=True, catalog_loaded=False
    )
    assert labels(steps) == ALL


def test_drift_checks_are_ignored_when_forced():
    """A forced reload re-runs step 1, which rebuilds the projection
    anyway — the drift reasons must not narrow it to step 3."""
    steps, reason = plan_steps(
        force=True, loaded=True, stale_mappings=5, unrouted=True, catalog_loaded=False
    )
    assert labels(steps) == ALL
    assert reason == "forced reload"


def test_reason_names_the_trigger():
    _, reason = plan_steps(
        force=False, loaded=True, stale_mappings=2, unrouted=True, catalog_loaded=False
    )
    assert "2 stop mapping(s)" in reason

    _, reason = plan_steps(
        force=False, loaded=True, stale_mappings=0, unrouted=True, catalog_loaded=False
    )
    assert "no routed geometry" in reason

    _, reason = plan_steps(
        force=False, loaded=True, stale_mappings=0, unrouted=False, catalog_loaded=True
    )
    assert reason == "already loaded"
