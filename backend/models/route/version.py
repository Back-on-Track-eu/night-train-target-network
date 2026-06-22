"""
version.py
==========
Version constant for the Night Train Route Builder model.

Bump this version when any change affects the Trip output:
  - Routing logic or GraphHopper configuration
  - Energy calculation method
  - Schedule / dwell time computation
  - Infrastructure related cost enrichment (TAC, energy, station charges)
  - Any change to the Trip, TripPath, TripStats, StopTime data model

The version is returned in every POST /api/route/build-route response
and stored in ParamsSnapshot on each Trip for reproducibility.
"""

ROUTE_BUILDER_VERSION: str = "1.0.0"

# TODO: Injected at build time by CI — do not edit manually.
# TODO: See .github/workflows/backend-tests.yml
# TODO: Add a description and input/ output values
GIT_SHA: str = "unknown"

CHANGELOG: dict = {
    "1.0.0": {
        "date":    "2026-06-23",
        "author":  "david",
        "changes": "Initial Phase 3 implementation. GTFS-aligned Route/Trip "
                   "domain model, TripPath with per-country cost enrichment, "
                   "schedule computation in route_factory.",
    },
}

# TODO: Add GitHub Actions version bump check to .github/workflows/backend-tests.yml
# Rule: if any file under backend/models/route/ changes (except version.py itself),
# ROUTE_BUILDER_VERSION must differ from the value on main branch.
# Suggested step:
#
#   - name: Check route builder version bump
#     run: |
#       CHANGED=$(git diff origin/main --name-only \
#         | grep "^backend/models/route/" \
#         | grep -v "version.py")
#       if [ -n "$CHANGED" ]; then
#         MAIN_VER=$(git show origin/main:backend/models/route/version.py \
#           | grep ROUTE_BUILDER_VERSION | cut -d'"' -f2)
#         CUR_VER=$(grep ROUTE_BUILDER_VERSION backend/models/route/version.py \
#           | cut -d'"' -f2)
#         if [ "$MAIN_VER" = "$CUR_VER" ]; then
#           echo "ERROR: models/route/ changed but ROUTE_BUILDER_VERSION not bumped ($CUR_VER)"
#           exit 1
#         fi
#       fi