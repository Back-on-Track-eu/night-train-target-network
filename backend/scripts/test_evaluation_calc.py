"""
test_evaluation_calc.py
========================
RETIRED (WP5, PROPOSALS_DESIGN.md §7.6): POST /api/evaluation/calc is
gone. This script existed to cost an already-built route_to_dict()
payload (optionally under a different scenario_id) — a capability the
merged POST /api/proposal/calc deliberately does not replace: it always
builds fresh from {stops, composition_id, ...} and runs the stopgap
demand model internally, with no way to hand it a pre-built route or
override its demand.

If you need this script's old capability for manual debugging:

  - Costing a FRESH route (build + evaluate together): use
    scripts/test_route_plan.py against POST /api/proposal/calc — its
    request/response now includes the evaluation alongside the route,
    no second call needed.

  - Costing an ALREADY-BUILT route under custom/injected demand, or a
    different scenario_id than it was planned with: no HTTP endpoint
    does this any more (by design — see PROPOSALS_DESIGN.md §2.1's
    "no persistence decisions" / stateless-compute rationale). Do it at
    the Python level instead, the same way the test suite now does
    (tests/helpers.py:compute_evaluation_domain(), used by
    tests/test_31_evaluation_content.py and tests/test_40_pipeline.py):

        from adapters.data_loader_from_db import DBDataLoader
        from tests.helpers import compute_evaluation_domain

        loader = DBDataLoader()
        route_dict = json.load(open("path/to/route.json"))  # a route_to_dict() payload
        costed, result = compute_evaluation_domain(
            route_dict, loader, demand=[("Seat", 40, 89.0)],
            scenario_id=None,  # or an explicit override
        )

    This runs the exact same evaluate_route()/views pipeline the old
    endpoint did, just called directly instead of over HTTP.
"""

import sys

if __name__ == "__main__":
    print(__doc__)
    sys.exit(1)
