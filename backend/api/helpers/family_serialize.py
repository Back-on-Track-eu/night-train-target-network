"""
family_serialize.py
===================
Domain → dict for the proposal family (adapters/family/README.md): the
§2.5 document POST /api/proposal/family returns and GET …/<key> serves
back, and the per-member error record. No DB access, no Flask.

What the document carries, and only once:

  request       the resolved echo (stops + HOW) — what publish sends back
  suggested     the presented member's suggestions ("suggest" only)
  axes          scenario variants (with their scenario's display fields)
                and composition ids — the catalog is GET /api/params
  geometries    content-addressed pool, ≈8 entries for 72 members
  routes        one compact route per (scenario, composition) — variants
                of one scenario evaluate the same route
  members       variants outer, compositions inner; ok members carry a
                route_ref and the §5.4 summary, error members the code
                /calc would answer
  stats         counts, elapsed, cache_hit, and the context's memo stats

Not here by design (D11): provenance, parameter blocks, the models
registry, per-member views, and — since D13 — route fingerprints. Views
are GET …/members/<sv>/<comp>/views; the fingerprint stays on
compute_proposal(), which publish and refresh call.

Public interface:
  family_document(result, family_key, request_echo, cache_hit) -> dict
  error_member(member, code, message, extra) -> dict
"""

from __future__ import annotations

from adapters.proposal.id_prefix import rewrite_id_prefix
from api.helpers.evaluation_serialize import route_view_to_dict
from api.helpers.route_serialize import (
    route_compact_to_dict,
    route_to_dict,
    suggested_stops_to_dicts,
)
from api.helpers.scenario_serialize import scenario_variant_to_dict
from models.evaluation.model import CALC_VERSION
from models.evaluation.summary import build_summary_row
from models.family.builder import FamilyMember, FamilyResult
from models.route.model import (
    NEUTRAL_PROPOSAL_ID,
    NEUTRAL_PROPOSAL_VERSION,
    ROUTE_BUILDER_VERSION,
)

_NEUTRAL_PREFIX = f"P{NEUTRAL_PROPOSAL_ID}_V{NEUTRAL_PROPOSAL_VERSION}_"

# Bump on ANY change to the document's shape — a key, a nesting, a dropped
# field. family.documents stores the serialised body, so a reshaped
# document must invalidate the cache exactly as a changed number does;
# models/family/key.py folds this into the family key, so old rows are
# never found again and the sweep drops them. Not a wire version the
# client reads: the frontend's types track the shape, and a document they
# can no longer parse must not be served at all.
#
#   1  WP18 B2a, first shape
#   2  stats.context nested — the build context's counters collided with
#      the document's own n_routes
FAMILY_DOCUMENT_FORMAT = 2


def route_ref(scenario_id: int, composition_id: str) -> str:
    return f"r:{scenario_id}:{composition_id}"


def error_member(
    member: FamilyMember, code: str, message: str, extra: dict | None = None
) -> dict:
    """The record for a member that did not compute. code/message/extra
    are classify_compute_error()'s, resolved by the caller (the API layer
    owns the exception → wire-code mapping)."""
    record = {
        "scenario_variant_id": member.scenario_variant_id,
        "composition_id": member.composition_id,
        "status": "error",
        "error": code,
        "message": message,
    }
    if extra:
        record.update(extra)
    return record


def family_document(
    result: FamilyResult,
    family_key: str,
    request_echo: dict,
    cache_hit: bool,
    error_records: dict[tuple[int, str], dict],
) -> dict:
    """Assemble the document. error_records maps (variant id, composition
    id) of every error member to its error_member() record — built by the
    caller, which can classify exceptions."""
    geometries: dict[str, list] = {}
    geometry_ids: dict[int, str] = {}
    routes: dict[str, dict] = {}
    members: list[dict] = []

    for member in result.members:
        key = (member.scenario_variant_id, member.composition_id)
        if member.status != "ok":
            members.append(error_records[key])
            continue

        ref = route_ref(member.scenario_id, member.composition_id)
        # The full dict first: the summary reads od_pairs and the
        # composition block, both of which the compact route drops. Built
        # once per route — variants of one scenario share it — and the
        # summary is per member, because measures change it.
        route_dict = route_to_dict(
            member.route, member.scenario_id, member.provenance.tracks
        )
        summary = build_summary_row(
            route_dict,
            {"views": {"route": route_view_to_dict(member.views.bd_all, member.route)}},
        )
        if ref not in routes:
            routes[ref] = rewrite_id_prefix(
                route_compact_to_dict(route_dict, geometries, geometry_ids),
                _NEUTRAL_PREFIX,
                "",
            )
        members.append(
            {
                "scenario_variant_id": member.scenario_variant_id,
                "composition_id": member.composition_id,
                "status": "ok",
                "route_ref": ref,
                "summary": summary,
            }
        )

    presented_variant, presented_composition = result.presented
    document = {
        "family_key": family_key,
        "route_builder_version": ROUTE_BUILDER_VERSION,
        "calc_version": CALC_VERSION,
        "request": request_echo,
    }
    if result.request.auto_stop_addition == "suggest":
        document["suggested_stops"] = suggested_stops_to_dicts(result.suggestions)
    document.update(
        {
            "axes": {
                "scenario_variants": [
                    scenario_variant_to_dict(v, result.axes.scenarios[v.scenario_id])
                    for v in result.axes.variants
                ],
                "compositions": [c.comp_id for c in result.axes.compositions],
            },
            "presented": {
                "scenario_variant_id": presented_variant,
                "composition_id": presented_composition,
            },
            "geometries": geometries,
            "routes": routes,
            "members": members,
            "stats": {
                "n_members": len(members),
                "n_ok": result.n_ok,
                "n_error": result.n_error,
                "n_routes": len(routes),
                "n_geometries": len(geometries),
                "elapsed_s": round(result.elapsed_s, 2),
                "cache_hit": cache_hit,
                # The context's own counters, nested rather than merged:
                # its "n_routes" counts distinct router calls (leg
                # variants), which is not this document's route count.
                "context": result.context_stats,
            },
        }
    )
    return document
