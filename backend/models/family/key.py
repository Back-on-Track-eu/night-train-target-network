"""
key.py
======
family_key(): which pins enter a family's identity, and nothing else.

A family is a pure function of its inputs, so two callers posting the
same inputs must land on the same document (adapters/family/
document_cache.py). What goes into the key is therefore exactly what can
change a member's numbers:

  - the resolved request: stops and every HOW field (timetable_mode,
    fixed_night_interval, schedule_mode, routing_mode, auto_stop_addition,
    the canonicalised expert_timetable) — as api/helpers/proposal_compute.
    py resolves it, so an omitted field and its explicit default hash
    alike;
  - the resolved axes: scenario_variant_ids and composition_ids, sorted —
    a variant id pins a scenario row and a measure set, and scenario rows
    are immutable, so the id already carries every parameter version;
  - ROUTE_BUILDER_VERSION and CALC_VERSION — a bump changes numbers, so it
    changes the key, and a stale document is simply never found again;
  - the document FORMAT version the caller passes in
    (api/helpers/family_serialize.py::FAMILY_DOCUMENT_FORMAT) — the cache
    stores a serialised document, so a change to its SHAPE has to
    invalidate it just as a change to its numbers does. Without this, a
    deploy that reshapes the document keeps serving the old shape for the
    length of the TTL and the client sees a body its types do not
    describe.

What stays out, by design: `presented` (which member the client shows is
presentation, not computation — choosing another must never rebuild),
and anything about the caller. auto_stop_addition IS in: a "suggest"
family carries suggestions an "off" family does not, and accepting one
posts a new stop list, which is a new family anyway.
"""

from __future__ import annotations

from models.evaluation.model import CALC_VERSION
from models.route.model import ROUTE_BUILDER_VERSION
from models.utils import canonical_sha256

# The resolved-request fields that shape a member. Listed rather than
# taking the whole dict so a field added to the echo for display reasons
# cannot silently start invalidating documents.
REQUEST_KEY_FIELDS = (
    "stops",
    "timetable_mode",
    "fixed_night_interval",
    "schedule_mode",
    "routing_mode",
    "auto_stop_addition",
    "expert_timetable",
)


def family_key(
    resolved_request: dict,
    scenario_variant_ids: list[int],
    composition_ids: list[str],
    document_format: int,
) -> str:
    """ "sha256:…" identity of one family — see the module docstring for
    what is and is not in it.

    document_format is passed in rather than imported: the shape belongs
    to the serializer (api/helpers/family_serialize.py), and models/ never
    imports from api/."""
    return canonical_sha256(
        {
            "request": {field: resolved_request[field] for field in REQUEST_KEY_FIELDS},
            "scenario_variant_ids": sorted(scenario_variant_ids),
            "composition_ids": sorted(composition_ids),
            "route_builder_version": ROUTE_BUILDER_VERSION,
            "calc_version": CALC_VERSION,
            "document_format": document_format,
        }
    )
