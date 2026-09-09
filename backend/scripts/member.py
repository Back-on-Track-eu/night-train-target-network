"""
member.py
=========
One member, in-process, for the host-run analysis scripts in this folder.

POST /api/proposal/calc is gone (WP18 B2b): the wire carries a family's
COMPACT route, and these scripts read the full one (segment from_stop/
to_stop, geometries). compute_member() — the same call behind the family's
views endpoint and publish — returns exactly what /calc did minus the
models registry and the parameters block, so the scripts run it here,
against the same singletons the API uses, resolved for the host by
dev_env.resolve_env(). The payload is passed through JSON once so it is
the dict a client would have received.

    from scripts.member import compute_member_payload
    payload = compute_member_payload({"stops": [...], "composition_id": "NEW-BAL-7"})
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dev_env  # noqa: E402

dev_env.resolve_env()

from api.helpers import dependencies  # noqa: E402
from api.helpers.member_compute import compute_member, validate_calc_body  # noqa: E402

_ready = False


def compute_member_payload(body: dict, use_cache: bool = True) -> dict:
    """The member payload for one request body, validated the way the API
    validates it. Domain errors (unroutable pair, gauge mismatch) propagate
    as the pipeline raises them."""
    global _ready
    errors = validate_calc_body(body)
    if errors:
        raise ValueError("; ".join(errors))
    if not _ready:
        dependencies.init()
        _ready = True
    payload, _ = compute_member(body, use_cache=use_cache)
    return json.loads(json.dumps(payload))
