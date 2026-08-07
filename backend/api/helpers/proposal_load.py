"""
proposal_load.py
=================
The on-load version-refresh fallback (PROPOSALS_DESIGN.md §4.2, WP8) as a
shared helper: load a proposal's container row and, if it has fallen
behind the running route_builder_version/calc_version or the current base
scenario, recompute and overwrite it in place before returning — so every
caller always sees the current-base, current-version state.

Extracted out of api/proposals.py's GET /api/proposal/<id> for WP9: the
compare endpoint's stored sides run the same fallback ("uses WP8's
on-load refresh", §10), and the compare endpoint's computed sides depend
on it too — an override side replays the anchor's stored compute_request,
which is only guaranteed to carry the current base scenario_id after this
refresh has run. One implementation, no drift.

Public interface:
  load_current_container(repo, proposal_id) -> dict | None
"""

from __future__ import annotations

from adapters.proposal.repository import outdated_trigger
from api.helpers.proposal_compute import compute_proposal


def load_current_container(repo, proposal_id: int) -> dict | None:
    """get_container() plus the §4.2 on-load refresh fallback. Returns the
    (possibly just-refreshed) container row, or None if the proposal_id is
    unknown. Every load is cheap in the common case — outdated_trigger()
    is an in-Python check on the row get_container() already fetched; only
    a genuinely stale proposal pays for a recompute here (once — the
    refresh persists, so the next load is current again)."""
    container = repo.get_container(proposal_id)
    if container is None:
        return None

    trigger = outdated_trigger(container)
    if trigger is not None:
        # Re-resolve scenario_id fresh against the current base rather
        # than replaying the stored (possibly stale) one — the whole
        # point of a refresh is to land back on whatever base is current
        # NOW, regardless of which of the three triggers actually fired.
        refresh_request = dict(container["compute_request"])
        refresh_request["scenario_id"] = None
        computed, _ = compute_proposal(refresh_request)
        repo.refresh_proposal(proposal_id, computed, detail=trigger)
        # refresh_proposal()'s own return dict is deliberately minimal
        # (identity + timestamps, mirroring publish()'s) — it doesn't
        # carry user_name/compute_request/evaluation_output the way
        # get_container() does, so re-fetch rather than hand-assembling
        # what the callers' response builders need.
        container = repo.get_container(proposal_id)

    return container
