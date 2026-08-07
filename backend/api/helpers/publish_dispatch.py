"""
publish_dispatch.py
====================
POST /api/proposal/publish's case-dispatch (adapters/proposal/README.md §2.2). All persisting case distinctions in one small component: validate
the publish envelope, enforce the base-scenario rule, compute (never
trust a client-supplied result), and hand off to
adapters/proposal/repository.py's publish() for the actual write.

Deliberately Flask-agnostic beyond taking user_id as a plain argument —
api/proposal_publish.py reads it off g.user_id (the auth layer) and
passes it in; db/dev/seed.py's example-proposal seed calls
dispatch_publish() directly the same way, with no Flask request context
at all. Only api/proposal_publish.py (the view) touches flask.g/request.

Public interface:
  validate_publish_body(body) -> list[str]
  dispatch_publish(body, user_id) -> dict   (raises ScenarioNotBaseError /
                                              adapters.proposal.repository.
                                              ProposalNotFoundError /
                                              ProposalForbiddenError /
                                              ValueError on failure)
"""

from __future__ import annotations

from api.helpers.dependencies import get_loader, get_proposal_repository
from api.helpers.proposal_compute import compute_proposal, validate_calc_body


class ScenarioNotBaseError(Exception):
    """Raised when compute_request.scenario_id resolves to something other
    than the current base scenario — §2.2's base-scenario rule."""


def validate_publish_body(body: dict) -> list[str]:
    """Structural validation of the publish envelope itself (§2.2) —
    compute_request's own fields are validated separately via
    proposal_compute.validate_calc_body(), since that's exactly the same
    request shape /calc already validates."""
    errors = []

    if not isinstance(body.get("name"), str) or not body["name"].strip():
        errors.append("'name' must be a non-empty string.")

    mode = body.get("mode")
    if mode not in ("new", "overwrite"):
        errors.append("'mode' must be 'new' or 'overwrite'.")

    proposal_id = body.get("proposal_id")
    if mode == "new" and proposal_id is not None:
        errors.append("'proposal_id' is forbidden when mode is 'new'.")
    if mode == "overwrite" and not isinstance(proposal_id, int):
        errors.append("'proposal_id' is required (integer) when mode is 'overwrite'.")

    based_on = body.get("based_on_proposal_id")
    if based_on is not None and not isinstance(based_on, int):
        errors.append("'based_on_proposal_id' must be an integer if provided.")

    compute_request = body.get("compute_request")
    if not isinstance(compute_request, dict):
        errors.append("'compute_request' must be an object.")
    else:
        errors.extend(validate_calc_body(compute_request))

    return errors


def dispatch_publish(body: dict, user_id: int) -> dict:
    """Validate (assumed already done by the caller via
    validate_publish_body() — this function re-derives nothing structural,
    only the base-scenario check below, which needs a DB round trip and so
    doesn't belong in the pure structural validator), enforce the
    base-scenario rule, compute, and publish.

    Returns adapters.proposal.repository.ProposalRepository.publish()'s
    result dict — ready for api/helpers/proposal_serialize.py to shape
    into the final HTTP response.
    """
    compute_request = body["compute_request"]
    mode = body["mode"]
    name = body["name"].strip()
    proposal_id = body.get("proposal_id")
    based_on_proposal_id = body.get("based_on_proposal_id")

    # Base-scenario rule (§2.2, locked decision 4): checked BEFORE the
    # (expensive, live-routing) compute below, so a non-base request fails
    # fast rather than paying for a build that will just be rejected.
    loader = get_loader()
    current_base = loader.resolve_scenario_id(None)
    requested_scenario = compute_request.get("scenario_id")
    if requested_scenario is not None and requested_scenario != current_base:
        raise ScenarioNotBaseError(requested_scenario, current_base)

    # Integrity rule (§2.2, locked decision 5): the server never persists
    # a client-supplied result — compute_request carries inputs only, the
    # result stored below always comes from compute_proposal(). A §2.3
    # cache hit satisfies the rule the same way a fresh compute does
    # (cached payloads are exclusively server-written), so the cache_hit
    # flag is irrelevant here — publish never exposes it.
    computed, _ = compute_proposal(compute_request)

    repo = get_proposal_repository()
    return repo.publish(
        mode=mode,
        user_id=user_id,
        name=name,
        computed=computed,
        proposal_id=proposal_id,
        based_on_proposal_id=based_on_proposal_id,
    )
