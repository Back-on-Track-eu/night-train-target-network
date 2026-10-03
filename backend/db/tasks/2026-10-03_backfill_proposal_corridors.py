"""Backfill proposals.proposal_corridors (§5.4b) for every proposal
published before backend 0.5.11 introduced the table.

Pure SQL over data already stored — the base route's GTFS tables and the
§5.4a scenario rows' `segments` — through the SAME repository method every
publish and refresh use (ProposalRepository._replace_corridors()), so a
backfilled proposal is indistinguishable from a freshly published one. No
routing engine involved; about a minute for a thousand proposals.

Idempotent: the work queue is list_corridor_gaps(), empty once every
proposal has rows for its stored version. Until it is empty,
POST /api/proposals' map_lines derives corridors at request time instead
of reading the table.
"""

DESCRIPTION = (
    "Precompute the gallery corridor pieces of every proposal that has none yet"
)


def run(ctx, dry_run: bool) -> str:
    repo = ctx.repo
    gaps = repo.list_corridor_gaps()
    if not gaps:
        return "nothing to do — every proposal has its corridor rows"
    if dry_run:
        return f"would rebuild corridors for {len(gaps)} proposal(s)"

    rows = 0
    failed = 0
    for gap in gaps:
        try:
            rows += repo.rebuild_corridors(gap["proposal_id"])
        except Exception:  # noqa: BLE001 — one bad proposal must not stop the rest
            failed += 1
            ctx.log.exception("corridors failed for proposal_id=%s", gap["proposal_id"])
    if failed:
        raise RuntimeError(
            f"{failed} of {len(gaps)} proposal(s) failed — see the log; "
            f"{rows} rows written for the others, rerun to retry the rest"
        )
    return f"{rows} corridor rows written for {len(gaps)} proposal(s)"
