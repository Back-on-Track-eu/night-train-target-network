"""
matrix_serialize.py
===================
Dict shaping for POST /api/proposal/calc/matrix (adapters/proposal/README.md
§2.5). Pure functions over the §2.1 compute payloads
api/helpers/proposal_compute.py produces — no DB access, no Flask, no
threading; orchestration lives in api/helpers/proposal_matrix.py.

The response is a sequence of typed records rather than one document:

  header  — once, first: versions, the resolved request, both axes, the
            cell count, and (detail "full") the static models block
  shared  — zero or more, each BEFORE the first cell referencing it
            (detail "full" only): a geometry coordinate path or a
            parameter block, content-addressed so identical content
            across cells is sent once
  cell    — one per grid position, in completion order; index = position
            in scenarios-outer × compositions-inner order
  done    — once, last: completion status and stats

NDJSON streams these one per line; the JSON document mode folds the same
records into one object (fold_matrix_records) — one record generator,
two encodings, so the two can never disagree.

Shared ids are "g:"/"p:" + the first 16 hex characters of the canonical
SHA-256 (api/helpers/proposal_compute.py canonical_sha256) of the KIND
plus the block: identical geometry across scenarios or compositions
collapses to one record regardless of which cell produced it first, while
two different kinds that happen to hold the same content (empty blocks in
a degenerate scenario) stay separate — a shared record is filed under its
kind, so a collision across kinds would leave one of them unresolvable.

Public interface:
  SharedPool                                  — content-addressed block store
  header_record(...)                          -> dict
  cell_record(index, scenario_id, composition_id, payload, cache_hit,
              detail, pool)                    -> (list[dict], dict)
  error_cell_record(index, scenario_id, composition_id, code, message,
                    extra)                      -> dict
  done_record(status, stats)                  -> dict
  composition_axis_entry(composition)         -> dict
  fold_matrix_records(records)                -> dict
"""

from __future__ import annotations

from typing import Iterable

from api.helpers.proposal_compute import canonical_sha256
from api.helpers.scenario_serialize import scenario_axis_entry
from models.params import Composition, Scenario

SHARED_KINDS = (
    "geometry",
    "track_infrastructures",
    "stop_infrastructures",
    "compositions",
)

_PARAMETER_KINDS = SHARED_KINDS[1:]


class SharedPool:
    """Content-addressed store of the blocks cells reference instead of
    carrying. put() returns the id and whether the block is new — the
    caller emits a `shared` record exactly when it is."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def put(self, kind: str, data) -> tuple[str, bool]:
        prefix = "g" if kind == "geometry" else "p"
        digest = canonical_sha256([kind, data])[len("sha256:") :]
        shared_id = f"{prefix}:{digest[:16]}"
        is_new = shared_id not in self._seen
        self._seen.add(shared_id)
        return shared_id, is_new


# =============================================================================
# Axes
# =============================================================================


def composition_axis_entry(composition: Composition) -> dict:
    """The composition as a matrix-axis entry: identity and the few
    fields a comparison table sorts and filters on. Everything else is
    on GET /api/params/compositions, which the frontend already holds."""
    places_by_class = dict(composition.places_by_class)
    return {
        "composition_id": composition.comp_id,
        "description": composition.comp_description,
        "material_strategy": composition.material_strategy,
        "operator_id": composition.operator_id,
        "operator_name": composition.operator_name,
        "hsr_allowed": composition.hsr_allowed,
        "max_speed_kmh": composition.max_speed_kmh,
        "places_by_class": places_by_class,
        "places_total": sum(places_by_class.values()),
    }


# =============================================================================
# Records
# =============================================================================


def header_record(
    *,
    route_builder_version: str,
    calc_version: str,
    request: dict,
    scenarios: list[Scenario],
    compositions: list[Composition],
    baseline_index: int,
    models: dict | None,
) -> dict:
    record = {
        "type": "header",
        "route_builder_version": route_builder_version,
        "calc_version": calc_version,
        "request": request,
        "axes": {
            "scenarios": [scenario_axis_entry(s) for s in scenarios],
            "compositions": [composition_axis_entry(c) for c in compositions],
        },
        "n_cells": len(scenarios) * len(compositions),
        "baseline_index": baseline_index,
    }
    if models is not None:
        record["models"] = models
    return record


def cell_record(
    *,
    index: int,
    scenario_id: int,
    composition_id: str,
    payload: dict,
    cache_hit: bool,
    detail: str,
    pool: SharedPool,
) -> tuple[list[dict], dict]:
    """One ok cell from a §2.1 compute payload. Returns (shared_records,
    cell): the shared records are the blocks this cell is the first to
    reference and must be emitted before it.

    summary level: the §5.4 summary block and the fingerprint only.
    full level additionally: suggested_stops (when present), the route
    with every segment.geometry_id rewritten to a shared "g:" id and
    route.geometries dropped, and the evaluation's views with the three
    parameter blocks replaced by "p:" references. The models block is on
    the header (static across cells)."""
    cell = {
        "type": "cell",
        "index": index,
        "scenario_id": scenario_id,
        "composition_id": composition_id,
        "status": "ok",
        "cache_hit": cache_hit,
        "route_fingerprint": payload["route_fingerprint"],
        "summary": payload["summary"],
    }
    if detail != "full":
        return [], cell

    shared: list[dict] = []
    if "suggested_stops" in payload:
        cell["suggested_stops"] = payload["suggested_stops"]

    route = dict(payload["route"])
    geometry_ids = {}
    for geometry in route.pop("geometries", []):
        shared_id, is_new = pool.put("geometry", geometry["coords"])
        geometry_ids[geometry["id"]] = shared_id
        if is_new:
            shared.append(
                {
                    "type": "shared",
                    "kind": "geometry",
                    "id": shared_id,
                    "data": geometry["coords"],
                }
            )
    route["trip_pairs"] = [
        {
            **pair,
            "outbound": _remap_trip_geometry(pair["outbound"], geometry_ids),
            "return_trip": _remap_trip_geometry(pair["return_trip"], geometry_ids),
        }
        for pair in route["trip_pairs"]
    ]
    cell["route"] = route

    parameters = payload["evaluation"]["input"]["parameters"]
    refs = {}
    for kind in _PARAMETER_KINDS:
        shared_id, is_new = pool.put(kind, parameters[kind])
        refs[kind] = shared_id
        if is_new:
            shared.append(
                {
                    "type": "shared",
                    "kind": kind,
                    "id": shared_id,
                    "data": parameters[kind],
                }
            )
    cell["evaluation"] = {
        "parameters_refs": refs,
        "views": payload["evaluation"]["views"],
    }
    return shared, cell


def _remap_trip_geometry(trip: dict, geometry_ids: dict[str, str]) -> dict:
    return {
        **trip,
        "segments": [
            {
                **seg,
                "geometry_id": geometry_ids.get(seg["geometry_id"], seg["geometry_id"]),
            }
            for seg in trip["segments"]
        ],
    }


def error_cell_record(
    *,
    index: int,
    scenario_id: int,
    composition_id: str,
    code: str,
    message: str,
    extra: dict,
) -> dict:
    return {
        "type": "cell",
        "index": index,
        "scenario_id": scenario_id,
        "composition_id": composition_id,
        "status": "error",
        "error": code,
        "message": message,
        **extra,
    }


def done_record(status: str, stats: dict) -> dict:
    return {"type": "done", "status": status, "stats": stats}


# =============================================================================
# Document mode
# =============================================================================


def fold_matrix_records(records: Iterable[dict]) -> dict:
    """The same records as one JSON object: header fields at the top
    level, shared blocks keyed by kind then id, cells sorted by index
    (stream order is completion order), stats from the done record."""
    document: dict = {}
    shared: dict[str, dict] = {}
    cells: list[dict] = []
    for record in records:
        kind = record["type"]
        if kind == "header":
            document.update({k: v for k, v in record.items() if k != "type"})
        elif kind == "shared":
            shared.setdefault(record["kind"], {})[record["id"]] = record["data"]
        elif kind == "cell":
            cells.append({k: v for k, v in record.items() if k != "type"})
        elif kind == "done":
            document["status"] = record["status"]
            document["stats"] = record["stats"]
    if shared:
        document["shared"] = shared
    document["cells"] = sorted(cells, key=lambda cell: cell["index"])
    return document
