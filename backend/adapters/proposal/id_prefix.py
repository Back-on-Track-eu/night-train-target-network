"""
id_prefix.py
============
The one shared utility of the P{proposal_id}_V{version}_ ID convention
(models/route/version.py's "ID convention" section): rewriting an ID
prefix across a whole serialized compute response. Used from both sides
of the boundary — api/helpers/proposal_compute.py strips the neutral
P0_V0_ prefix for POST /api/proposal/calc's response, and
adapters/proposal/repository.py mints the real prefix at publish time —
so it lives in its own module rather than either caller.

Public interface:
  rewrite_id_prefix(obj, old_prefix, new_prefix) -> obj
"""

from __future__ import annotations

from typing import Any


def rewrite_id_prefix(obj: Any, old_prefix: str, new_prefix: str) -> Any:
    """Recursively replace an ID prefix in every string value AND dict key
    of a JSON structure. Covers route_id, trip_ids, geometry_ids, and all
    trip references (od_pairs, shuntings, parkings) as values — and, in
    the evaluation response's per-trip-pair/per-stop views
    (api/helpers/evaluation_serialize.py), trip_id/pair-key strings used
    as dict keys rather than values (e.g. data[pair_key][country_key]).
    Keys are always strings in a JSON-compatible dict, so the same
    startswith/replace logic applies to both.

    old_prefix must be non-empty and precise — every caller in this
    codebase uses either the neutral P0_V0_ prefix or the bare "R1"
    structural prefix, both of which are guaranteed not to collide with
    any other string in a compute response (stop names, country codes,
    etc. never start with either). An empty old_prefix would match every
    string in the structure, which is never what a caller wants."""
    if isinstance(obj, str):
        return (
            new_prefix + obj[len(old_prefix) :] if obj.startswith(old_prefix) else obj
        )
    if isinstance(obj, list):
        return [rewrite_id_prefix(item, old_prefix, new_prefix) for item in obj]
    if isinstance(obj, dict):
        return {
            rewrite_id_prefix(key, old_prefix, new_prefix): rewrite_id_prefix(
                value, old_prefix, new_prefix
            )
            for key, value in obj.items()
        }
    return obj
