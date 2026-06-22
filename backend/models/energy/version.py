"""
version.py
==========
Version constant for the energy model. Bump this version when any change
affects the energy calculation.

The version is returned in every POST /api/route/build-route response
and stored in ParamsSnapshot on each Trip for reproducibility.
"""

ENERGY_CALC_VERSION: str = "1.0.0"

# TODO Injected at build time by CI — do not edit manually.
# TODO See .github/workflows/backend-tests.yml
# TODO: Add a description and input/ output values
# TODO: Add kassenzettel calculation
GIT_SHA: str = "unknown"

CHANGELOG: dict = {
    "1.0.0": {
        "date":    "2026-06-23",
        "author":  "david",
        "changes": "Initial dummy implementation: flat 28.0 kWh/km factor. "
                   "Does not account for weight, speed, or terrain. "
                   "Requires replacement by energy model team — see "
                   "models/energy/calc_energy_consumption.py.",
    },
}

# TODO: Add GitHub Actions version bump check to .github/workflows/backend-tests.yml
# Rule: if any file under backend/models/energy/ changes (except version.py itself),
# ENERGY_CALC_VERSION must differ from the value on main branch.
# Suggested step:
#
#   - name: Check energy model version bump
#     run: |
#       CHANGED=$(git diff origin/main --name-only \
#         | grep "^backend/models/energy/" \
#         | grep -v "version.py")
#       if [ -n "$CHANGED" ]; then
#         MAIN_VER=$(git show origin/main:backend/models/energy/version.py \
#           | grep ENERGY_CALC_VERSION | cut -d'"' -f2)
#         CUR_VER=$(grep ENERGY_CALC_VERSION backend/models/energy/version.py \
#           | cut -d'"' -f2)
#         if [ "$MAIN_VER" = "$CUR_VER" ]; then
#           echo "ERROR: models/energy/ changed but ENERGY_CALC_VERSION not bumped ($CUR_VER)"
#           exit 1
#         fi
#       fi