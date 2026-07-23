#!/usr/bin/env bash
# =============================================================================
# One-command local instance of the Target Network deploy stack.
#
#   ./local.sh            (or: ./local.sh up)   → http://localhost:8080
#   ./local.sh down       stop, keep the database
#   ./local.sh reset      stop + wipe the database volume
#   ./local.sh logs       follow api logs
#
# This runs the SAME docker-compose.yml the servers run, plus a local Caddy
# (docker-compose.local.yml) that plays bot-server's vhost role, so the
# browser at localhost:8080 sees exactly what production serves. First boot
# is detected via the database volume and handles seed + migration baseline
# automatically, in the only order that works (seed first — it drops and
# recreates the schemas, tracking table included).
#
# For daily backend development use backend/docker/docker-compose.yml
# instead (it includes a local routing engine). This stack is for
# rehearsing/validating the server deploy: no routing engine, so route
# PLANNING fails locally — health, data, auth, proposals all work.
# =============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -f .env ]; then
    sed -e "s/^POSTGRES_PASSWORD=$/POSTGRES_PASSWORD=$(openssl rand -hex 12)/" \
        -e "s/^JWT_SECRET=$/JWT_SECRET=$(openssl rand -hex 32)/" \
        .env.example > .env
    chmod 600 .env
    echo "local.sh: generated .env (staging names, dev-mode mail — no editing needed)"
fi

# shellcheck disable=SC1091
source .env

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.local.yml"

case "${1:-up}" in
    up)
        # The server compose expects these as external; create locally.
        docker network create nextcloud_nextcloud  2>/dev/null || true
        docker network create targetnetwork_default 2>/dev/null || true

        FIRST_BOOT=no
        docker volume inspect "tn_${ENV_NAME}_pgdata" >/dev/null 2>&1 || FIRST_BOOT=yes

        $COMPOSE build
        if [ "$FIRST_BOOT" = yes ]; then
            echo "local.sh: first boot — seeding, then baselining migrations..."
            $COMPOSE up -d --wait db   # --wait: block until the healthcheck passes
                                       # (seed runs with --no-deps, so nothing else
                                       # would wait for the db on a fresh volume)
            $COMPOSE run --rm --no-deps api python db/dev/seed.py
            $COMPOSE run --rm migrate python db/migrate.py --baseline
        fi
        $COMPOSE up -d

        echo "local.sh: waiting for api health..."
        for _ in $(seq 1 24); do
            if curl -sf "http://127.0.0.1:${API_DEBUG_PORT}/api/health" > /dev/null; then
                echo ""
                echo "  ✓ up:  http://localhost:${LOCAL_HTTP_PORT:-8090}            (full app via local Caddy)"
                echo "    api: http://127.0.0.1:${API_DEBUG_PORT}/api/health"
                echo "    db:  127.0.0.1:${DB_DEBUG_PORT} (user ${POSTGRES_USER})"
                exit 0
            fi
            sleep 5
        done
        echo "local.sh: api did not become healthy — recent logs:" >&2
        $COMPOSE logs --tail 30 api >&2
        exit 1
        ;;
    down)
        $COMPOSE down
        ;;
    reset)
        $COMPOSE down -v
        echo "local.sh: database volume wiped — next 'up' re-seeds."
        ;;
    logs)
        $COMPOSE logs -f api
        ;;
    *)
        echo "usage: ./local.sh [up|down|reset|logs]" >&2
        exit 64
        ;;
esac
