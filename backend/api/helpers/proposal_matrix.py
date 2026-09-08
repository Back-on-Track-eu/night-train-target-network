"""
proposal_matrix.py
==================
Validation + orchestration for POST /api/proposal/calc/matrix
(adapters/proposal/README.md §2.5): one route computed under every
selected scenario × every selected composition, delivered as typed
records (api/helpers/matrix_serialize.py) so the view can stream them
as NDJSON or fold them into one JSON document.

Every cell is an ordinary compute_proposal() call (api/helpers/
proposal_compute.py): same validation of the HOW fields, same §2.3
compute cache — so a drill-down /calc on any cell afterwards is a cache
hit, and a second matrix over the same route is served entirely from
cache. The WHAT fields differ: instead of one composition_id/scenario_id
the request names axes, or leaves them out for the defaults
(composition axis = whole catalog, scenario axis = current base + every
current what-if; superseded scenarios only when named explicitly).

Ordering and concurrency (needs WP14's pooled adapters):
  - the baseline cell — (base scenario, DEFAULT_COMPOSITION_ID) when both
    are on the axes, else (scenarios[0], compositions[0]) — runs first,
    synchronously, so the first result is fast and the segment cache is
    warm before workers live-route the same legs concurrently;
  - the remaining cells run on a ThreadPoolExecutor of
    config.CALC_MATRIX_WORKERS and are emitted as they complete;
  - a cell failure never fails the request: it becomes a cell with
    status "error" carrying the same code /calc would answer
    (classify_compute_error); a fatal executor failure ends the stream
    with a done record of status "aborted";
  - closing the generator (client disconnect) cancels queued cells;
    running ones finish and still warm the cache.

Public interface:
  validate_matrix_body(body) -> list[str]
  resolve_matrix_axes(body, loader) -> MatrixAxes      (raises MatrixAxisError)
  iter_matrix_records(body, loader=None) -> Iterator[dict]
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterator

from api.config import CALC_MATRIX_MAX_CELLS, CALC_MATRIX_WORKERS
from api.helpers.dependencies import get_loader
from api.helpers.evaluation_serialize import models_to_dict
from api.helpers.matrix_serialize import (
    SharedPool,
    cell_record,
    done_record,
    error_cell_record,
    header_record,
)
from api.helpers.proposal_compute import (
    classify_compute_error,
    compute_proposal,
    normalize_expert_timetable,
    validate_how_fields,
)
from models.evaluation.model import CALC_VERSION
from models.params import Composition, Scenario
from models.route.model import (
    DEFAULT_AUTO_STOP_ADDITION,
    DEFAULT_COMPOSITION_ID,
    DEFAULT_ROUTING_MODE,
    DEFAULT_SCHEDULE_MODE,
    DEFAULT_TIMETABLE_MODE,
    ROUTE_BUILDER_VERSION,
)

logger = logging.getLogger(__name__)

VALID_DETAIL_LEVELS = frozenset({"summary", "full"})
DEFAULT_DETAIL = "summary"

# The HOW fields a cell inherits from the matrix request unchanged — the
# same subset validate_how_fields() checks.
_HOW_FIELDS = (
    "timetable_mode",
    "fixed_night_interval",
    "schedule_mode",
    "routing_mode",
    "auto_stop_addition",
    "expert_timetable",
)


class MatrixAxisError(ValueError):
    """An explicit axis names something the catalog does not have, or the
    grid exceeds CALC_MATRIX_MAX_CELLS — a 400 for the view."""


@dataclass
class MatrixAxes:
    scenarios: list[Scenario]
    compositions: list[Composition]

    @property
    def n_cells(self) -> int:
        return len(self.scenarios) * len(self.compositions)

    def cell_index(self, scenario_position: int, composition_position: int) -> int:
        return scenario_position * len(self.compositions) + composition_position

    def baseline(self) -> tuple[int, int]:
        """(scenario position, composition position) of the cell that runs
        first — the current base with the standard composition when both
        are on the axes, else the first of each."""
        scenario_pos = next(
            (i for i, s in enumerate(self.scenarios) if s.is_current_base), 0
        )
        composition_pos = next(
            (
                i
                for i, c in enumerate(self.compositions)
                if c.comp_id == DEFAULT_COMPOSITION_ID
            ),
            0,
        )
        return scenario_pos, composition_pos


# =============================================================================
# Validation
# =============================================================================


def validate_matrix_body(body: dict) -> list[str]:
    """Shape checks that need no DB: stops, the two optional axis lists,
    detail, and the HOW fields via the shared validator. Catalog
    membership and the cell cap are resolve_matrix_axes()'s job."""
    errors = []

    stops = body.get("stops")
    if not isinstance(stops, list):
        errors.append("'stops' must be a list of stop_id strings.")
    elif len(stops) < 2:
        errors.append("'stops' must contain at least 2 entries.")
    elif not all(isinstance(s, str) for s in stops):
        errors.append("'stops' must be a list of stop_id strings.")

    errors.extend(_validate_axis(body, "composition_ids", str))
    errors.extend(_validate_axis(body, "scenario_ids", int))

    detail = body.get("detail", DEFAULT_DETAIL)
    if detail not in VALID_DETAIL_LEVELS:
        errors.append(
            f"'detail' = '{detail}' is invalid. Must be one of: "
            f"{sorted(VALID_DETAIL_LEVELS)}."
        )

    errors.extend(validate_how_fields(body, stops))
    return errors


def _validate_axis(body: dict, key: str, item_type: type) -> list[str]:
    """null/omitted → default axis; a list must be non-empty, typed and
    free of duplicates (a duplicate would compute the same cell twice
    and make `index` ambiguous)."""
    axis = body.get(key)
    if axis is None:
        return []
    if not isinstance(axis, list) or not all(
        isinstance(x, item_type) and not isinstance(x, bool) for x in axis
    ):
        return [f"'{key}' must be null or a list of {item_type.__name__}s."]
    if not axis:
        return [
            f"'{key}' must not be empty — omit it or pass null for the default axis."
        ]
    if len(set(axis)) != len(axis):
        return [f"'{key}' contains duplicates."]
    return []


# =============================================================================
# Axis resolution
# =============================================================================


def resolve_matrix_axes(body: dict, loader) -> MatrixAxes:
    """Turn the request's axis lists (or their absence) into ordered
    domain objects. Order is the grid order cells are indexed by:
    scenarios as GET /api/scenarios lists them (base first, then by
    key), compositions in catalog order — an explicit list keeps the
    caller's order instead."""
    scenarios = _resolve_scenario_axis(body.get("scenario_ids"), loader)
    compositions = _resolve_composition_axis(body.get("composition_ids"), loader)
    axes = MatrixAxes(scenarios=scenarios, compositions=compositions)
    if axes.n_cells > CALC_MATRIX_MAX_CELLS:
        raise MatrixAxisError(
            f"{len(scenarios)} scenarios × {len(compositions)} compositions = "
            f"{axes.n_cells} cells exceeds CALC_MATRIX_MAX_CELLS "
            f"({CALC_MATRIX_MAX_CELLS}); narrow one axis."
        )
    return axes


def _resolve_scenario_axis(scenario_ids: list[int] | None, loader) -> list[Scenario]:
    by_id = {s.scenario_id: s for s in loader.list_all_scenarios()}
    if scenario_ids is None:
        current = [s for s in by_id.values() if s.is_current_scenario]
        # Base first, then the what-ifs by key — GET /api/scenarios' order.
        return sorted(current, key=lambda s: (not s.is_current_base, s.scenario_key))
    unknown = [sid for sid in scenario_ids if sid not in by_id]
    if unknown:
        raise MatrixAxisError(f"Unknown scenario_ids: {unknown}.")
    return [by_id[sid] for sid in scenario_ids]


def _resolve_composition_axis(
    composition_ids: list[str] | None, loader
) -> list[Composition]:
    catalog = loader.build_all_compositions(include_indicative=False).all()
    if composition_ids is None:
        return list(catalog.values())
    unknown = [cid for cid in composition_ids if cid not in catalog]
    if unknown:
        raise MatrixAxisError(f"Unknown composition_ids: {unknown}.")
    return [catalog[cid] for cid in composition_ids]


# =============================================================================
# Record generator
# =============================================================================


def iter_matrix_records(body: dict, loader=None) -> Iterator[dict]:
    """header, then the baseline cell, then every other cell as it
    completes (each preceded by the shared blocks it is the first to
    reference), then done. Raises MatrixAxisError before the first record
    only — after that, failures are records."""
    loader = loader if loader is not None else get_loader()
    axes = resolve_matrix_axes(body, loader)
    detail = body.get("detail", DEFAULT_DETAIL)
    request = _resolved_request(body, axes, detail)
    base_pos, comp_pos = axes.baseline()
    baseline_index = axes.cell_index(base_pos, comp_pos)

    yield header_record(
        route_builder_version=ROUTE_BUILDER_VERSION,
        calc_version=CALC_VERSION,
        request=request,
        scenarios=axes.scenarios,
        compositions=axes.compositions,
        baseline_index=baseline_index,
        models=models_to_dict() if detail == "full" else None,
    )

    pool = SharedPool()
    stats = {"n_cells": axes.n_cells, "n_ok": 0, "n_error": 0, "n_cache_hit": 0}
    started = time.monotonic()

    def cell_body(scenario: Scenario, composition: Composition) -> dict:
        return {
            "stops": list(body["stops"]),
            "composition_id": composition.comp_id,
            "scenario_id": scenario.scenario_id,
            **{key: body.get(key) for key in _HOW_FIELDS if key in body},
        }

    def emit(index: int, scenario: Scenario, composition: Composition, outcome):
        payload_or_exc, cache_hit = outcome
        if isinstance(payload_or_exc, BaseException):
            classified = classify_compute_error(payload_or_exc)
            if classified is None:
                logger.exception(
                    "calc/matrix cell %d failed (unexpected)",
                    index,
                    exc_info=payload_or_exc,
                )
                code, extra = "calc_error", {}
            else:
                code, _, extra = classified
            stats["n_error"] += 1
            yield error_cell_record(
                index=index,
                scenario_id=scenario.scenario_id,
                composition_id=composition.comp_id,
                code=code,
                message=str(payload_or_exc),
                extra=extra,
            )
            return
        stats["n_ok"] += 1
        stats["n_cache_hit"] += int(cache_hit)
        shared, cell = cell_record(
            index=index,
            scenario_id=scenario.scenario_id,
            composition_id=composition.comp_id,
            payload=payload_or_exc,
            cache_hit=cache_hit,
            detail=detail,
            pool=pool,
        )
        yield from shared
        yield cell

    def run(cell: dict) -> tuple:
        try:
            return compute_proposal(cell, loader=loader)
        except Exception as exc:  # per-cell errors are records, never raises
            return exc, False

    grid = [
        (axes.cell_index(si, ci), scenario, composition)
        for si, scenario in enumerate(axes.scenarios)
        for ci, composition in enumerate(axes.compositions)
    ]
    baseline = grid[baseline_index]
    yield from emit(*baseline, run(cell_body(baseline[1], baseline[2])))

    remaining = [entry for entry in grid if entry[0] != baseline_index]
    status = "complete"
    executor = ThreadPoolExecutor(max_workers=max(1, CALC_MATRIX_WORKERS))
    try:
        futures = {
            executor.submit(run, cell_body(scenario, composition)): (
                index,
                scenario,
                composition,
            )
            for index, scenario, composition in remaining
        }
        for future in as_completed(futures):
            index, scenario, composition = futures[future]
            yield from emit(index, scenario, composition, future.result())
    except BaseException:
        # GeneratorExit on client disconnect, or an executor failure:
        # either way the queued cells are dropped, running ones finish.
        status = "aborted"
        raise
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        stats["elapsed_s"] = round(time.monotonic() - started, 1)
        if status == "aborted":
            logger.info("calc/matrix aborted after %s", stats)
    yield done_record(status, stats)


def _resolved_request(body: dict, axes: MatrixAxes, detail: str) -> dict:
    """The request echo on the header — axes resolved to explicit ids,
    HOW defaults applied, same canonical form as /calc's echo so a cell
    can be replayed on /calc by adding its composition_id/scenario_id."""
    return {
        "stops": list(body["stops"]),
        "composition_ids": [c.comp_id for c in axes.compositions],
        "scenario_ids": [s.scenario_id for s in axes.scenarios],
        "detail": detail,
        "timetable_mode": body.get("timetable_mode", DEFAULT_TIMETABLE_MODE),
        "fixed_night_interval": body.get("fixed_night_interval"),
        "schedule_mode": body.get("schedule_mode", DEFAULT_SCHEDULE_MODE),
        "routing_mode": body.get("routing_mode", DEFAULT_ROUTING_MODE),
        "auto_stop_addition": body.get(
            "auto_stop_addition", DEFAULT_AUTO_STOP_ADDITION
        ),
        "expert_timetable": normalize_expert_timetable(body.get("expert_timetable")),
    }
