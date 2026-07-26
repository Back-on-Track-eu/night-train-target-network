#!/usr/bin/env bash
# =============================================================================
# Server-side deploy for one Target Network environment.
# Called by GitHub Actions (via the forced-command dispatch key) on every
# push to this checkout's branch — or by hand from inside the checkout:
#
#   /opt/targetnetwork-staging/deploy/bot-server-app/deploy.sh
#
# What it does, in order:
#   1. fast-forward the checkout to its branch head (refuses on divergence)
#   2. build + start the stack; the migrate one-shot applies pending SQL
#      migrations before the api container is allowed to start
#   3. assert no migrations are left pending (belt and braces)
#   4. wait for /api/health to answer through the localhost debug bind
#
# Any failure exits non-zero, which fails the Actions run — a broken deploy
# is a red X on the commit, never a silent half-state.
# =============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$APP_DIR/../.." && pwd)"

cd "$REPO_DIR"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "deploy: $REPO_DIR on branch $BRANCH"
git pull --ff-only

cd "$APP_DIR"
# shellcheck disable=SC1091
source .env   # for API_DEBUG_PORT / ENV_NAME in the checks below

docker compose up -d --build

echo "deploy: asserting migrations are current..."
docker compose run --rm migrate python db/migrate.py --check

echo "deploy: waiting for api health..."
for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${API_DEBUG_PORT}/api/health" > /dev/null; then
        echo "deploy: $ENV_NAME healthy at $(git -C "$REPO_DIR" rev-parse --short HEAD)."
        exit 0
    fi
    sleep 5
done

echo "deploy: FAILED — api did not become healthy within 150s." >&2
echo "deploy: recent api logs:" >&2
docker compose logs --tail 40 api >&2
exit 1
