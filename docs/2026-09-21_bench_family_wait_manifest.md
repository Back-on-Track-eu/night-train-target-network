# bench_family_wait.py — delivery manifest

Date: 2026-09-21 · Scope: **one new dev script**, no app change, no version bump.

| File | Change |
|---|---|
| **new** `backend/scripts/bench_family_wait.py` | Measures what the builder waits for: wall time of `POST /api/proposal/family` over HTTP beside the response's own `stats`. Four runs per route — *first* (live routing for never-routed pairs), *cold* (new family key, legs cached), *hit* (document cache), *narrow* (one scenario × two compositions) — then a least-squares fit `base + per_leg × legs + per_member × members` over the cold and narrow runs, the live-routing premium per route, and the median cache hit. Feeds the expected-duration model for the "taking longer than usual" escalation. |

Run host-side against the dev stack:

    cd backend
    uv run python -m scripts.bench_family_wait

A new family key is forced with a random `passengers_per_year` — part of the key,
free in routing — so repeated runs never measure a stale document cache. The
*first* runs only route live the very first time a stop pair meets a graph; on
a rerun they match *cold*, which the premium line makes visible.
