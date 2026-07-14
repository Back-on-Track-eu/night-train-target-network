# Demo/dev stack on bot-server (second instance)

Runs **current `main`** (backend + Vue frontend incl. the cost-revenue
breakdown from PR #12) next to the untouched June-23 prod stack, with its
own Postgres. Covers two board cards: *"Set-up test database on hetzner
server as a second instance"* (Stream 2) and *"Initial deployment of first
view on back on track server"* (Stream 3).

**URL:** https://targetnetwork.65.109.137.97.sslip.io (basic-auth
`volunteer` / password in Vaultwarden → Target Network org).

## Design

| Piece | Choice | Why |
|---|---|---|
| DB | own `tn-demo-db` (PostGIS 16), fresh volume | prod DB schema is frozen at 23-Jun vintage (no `scenario` schema); a fresh volume gets all 5 current schemas + seed |
| Routing | **reuses** prod `targetnetwork-routing` | stateless per request; `config.yml` + `custom_models/` identical between the 23-Jun build and main (verified 2026-07-14); a second 3-4 GB JVM doesn't fit the box |
| API | gunicorn 2 workers, `command:` override | the image's default entrypoint runs `seed.py` (starts with `DROP SCHEMA … CASCADE`) on every boot — never let that be the default in a long-lived stack |
| Frontend | static Vite build behind nginx (`frontend/Dockerfile.demo`) | the default Dockerfile is a dev server; `VITE_API_BASE_URL=""` bakes same-origin `/api/*` calls, Caddy routes them |

## First-time setup

```bash
# from the Mac (private repo, rsync lane — no git auth on the box):
rsync -az --delete --exclude '.git' --exclude 'node_modules' \
  ~/Documents/Projects/night-train-target-network/ \
  bot-server:/opt/targetnetwork-demo/

ssh bot-server
cd /opt/targetnetwork-demo/deploy/bot-server-demo
cp .env.example .env && vim .env && chmod 600 .env
docker compose build
docker compose up -d db
docker compose run --rm api python db/dev/seed.py   # one-time seed (3-scenario layout, 50 stops)
docker compose up -d
```

Startup order matters: `api`'s `create_app()` builds a CountryIndex from
`input_params.countries` at boot — seed **before** first `up -d api`, or
the workers crash-loop on an empty table.

## Caddy vhost (in /opt/nextcloud/caddy/Caddyfile)

Replace the body of the existing `targetnetwork.65.109.137.97.sslip.io`
block (it still points at the removed `targetnetwork-frontend:5173`):

```caddy
targetnetwork.65.109.137.97.sslip.io {
	basic_auth {
		volunteer <keep-existing-hash>
	}
	handle /api/* {
		reverse_proxy tn-demo-api:5000
	}
	handle {
		reverse_proxy tn-demo-frontend:80
	}
}
```

> ⚠️ On this box `caddy reload` does **not** reliably apply Caddyfile
> changes — always `docker restart nextcloud-caddy` (also re-triggers the
> sslip.io Let's Encrypt cert when needed). Back up the Caddyfile first.

## Update to latest main

```bash
# Mac: rsync as above, then on the box:
cd /opt/targetnetwork-demo/deploy/bot-server-demo
docker compose up -d --build api frontend    # do NOT touch db
```

Schema changed on main? Reset the demo DB (it holds no precious data):
`docker compose down db && docker volume rm targetnetwork-demo_tn_demo_pgdata`,
then redo the db/seed steps above.

## Smoke test

```bash
curl -s localhost:5056/api/health
curl -s localhost:5056/api/scenarios | head -c 300
curl -s -X POST localhost:5056/api/route/plan -H 'Content-Type: application/json' \
  -d '{"stops":["DE_BERLIN_HBF","AT_WIEN_HBF"],"composition_id":"STD-7.1","proposal_id":900,"proposal_version":1}' \
  | head -c 300   # exercises the shared routing engine incl. custom_model
```

## Teardown

```bash
docker compose down          # keep the DB volume
docker compose down -v       # full reset
```

Prod stack (`/opt/targetnetwork`) is untouched by all of the above.
