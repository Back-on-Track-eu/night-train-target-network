"""
version.py
==========
Version constant for the Night Train Cost/Revenue Evaluation model.

Bump this version when any change affects the EvaluationResult output:
  - Revenue calculation logic
  - Cost breakdown logic
  - Class cost allocation logic
  - Any change to EvaluationResult, TripResult, RevenueBreakdown,
    CostBreakdown, ClassCostAllocation data model

The version is returned in every POST /api/evaluate response.
"""

CALC_VERSION: str = "1.0.0"

# TODO Injected at build time by CI — do not edit manually.
# TODO See .github/workflows/backend-tests.yml
# TODO: Add a description and input/ output values
# TODO: Add kassenzettel..
GIT_SHA: str = "unknown"

CHANGELOG: dict = {
    "1.0.0": {
        "date":    "2026-06-23",
        "author":  "david",
        "changes": "Initial Phase 3 implementation. Split from monolithic "
                   "run_model.py into evaluate_route() entry point. "
                   "ModelResult replaced by TripResult (per-trip) + "
                   "EvaluationResult (route-level aggregate). "
                   "parking_eur moved to route level.",
    },
}

# TODO: Add GitHub Actions version bump check to .github/workflows/backend-tests.yml
# Rule: if any file under backend/models/cost_rev_eval/ changes (except version.py
# itself), CALC_VERSION must differ from the value on main branch.
# Suggested step:
#
#   - name: Check cost/rev eval version bump
#     run: |
#       CHANGED=$(git diff origin/main --name-only \
#         | grep "^backend/models/cost_rev_eval/" \
#         | grep -v "version.py")
#       if [ -n "$CHANGED" ]; then
#         MAIN_VER=$(git show origin/main:backend/models/cost_rev_eval/version.py \
#           | grep CALC_VERSION | cut -d'"' -f2)
#         CUR_VER=$(grep CALC_VERSION backend/models/cost_rev_eval/version.py \
#           | cut -d'"' -f2)
#         if [ "$MAIN_VER" = "$CUR_VER" ]; then
#           echo "ERROR: models/cost_rev_eval/ changed but CALC_VERSION not bumped ($CUR_VER)"
#           exit 1
#         fi
#       fi