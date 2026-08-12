"""
proposal_stats.py
=================
GET /api/proposals/stats — descriptive statistics over the gallery
(adapters/proposal/README.md §7.7).

Answers three questions about what has been proposed so far, each split
into proposals / existing trains / both:

  * how many there are (rows, plus distinct stops and countries reached)
  * what their KPIs look like in aggregate (count/avg/min/max, and a sum
    where summing means something)
  * which countries and country-to-country relations are served most and
    least — the second ranked over the routable candidate set in
    input_params.country_relations, so an unserved relation can appear
    at zero and a relation no train could physically make does not
    appear at all

Read-only and unauthenticated, same policy as the other GETs. Nothing is
recomputed: every number comes off proposals.proposal_summaries ∪
ontd.route_summaries. The bundle economics of a SET of proposals —
re-derived intensive quantities, live computes per member — is a
different endpoint (POST /api/proposals/analyze, parked in
docs/PARKED_WORK.md).
"""

import logging

from flask import Blueprint, jsonify, request

from api import config
from api.helpers.dependencies import get_proposal_repository
from api.helpers.proposal_stats import (
    filters_for,
    stats_to_dict,
    validate_stats_query,
)

logger = logging.getLogger(__name__)
bp = Blueprint("proposal_stats", __name__)


@bp.get("/proposals/stats")
def proposal_stats():
    """Statistics over every stored proposal and existing train, or over
    one user's proposals.

    Query parameters:
      user_id  int, optional — narrow to this user's proposals. Implies
                               sources=["proposal"]; an unknown id is an
                               empty result, not a 404 (this is an
                               aggregate, not a resource lookup).

    List lengths (config.PROPOSALS_STATS_COUNTRY_TOP / _FLOP) and the
    relation distance threshold (config.PROPOSALS_STATS_RELATION_MAX_KM)
    are deployment settings, not request parameters — they define what
    "top" and "flop" mean, and that definition should not vary per
    caller.
    """
    defaults = {"user_id": None}
    params, errors = validate_stats_query(request.args, defaults)
    if errors:
        return jsonify({"error": "validation_error", "details": errors}), 400

    user_id = params["user_id"]
    filters = filters_for(user_id)
    max_relation_km = config.PROPOSALS_STATS_RELATION_MAX_KM

    repo = get_proposal_repository()
    payload = stats_to_dict(
        user_id=user_id,
        kpi_rows=repo.stats_kpis(filters),
        reach_rows=repo.stats_reach(filters),
        country_rows=repo.stats_country_counts(filters),
        relation_rows=repo.stats_relation_counts(filters, max_relation_km),
        universe=repo.stats_relation_universe(max_relation_km),
        top=config.PROPOSALS_STATS_COUNTRY_TOP,
        flop=config.PROPOSALS_STATS_COUNTRY_FLOP,
        max_relation_km=max_relation_km,
    )
    return jsonify(payload), 200
