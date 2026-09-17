# Coolify deployment (tn-server, since 2026-09-16)

The dedicated Target Network box (`tn-server`, Hetzner auction #3065458, 95.216.39.96,
HEL1) runs **Coolify** (`https://coolify.95.216.39.96.sslip.io`, later `coolify.tn.back-on-track.eu`).
Host provisioning and lifecycle live in `Back-on-Track-eu/bot-server-infrastructure`
under `hosts/tn-server/`; **this directory is what Coolify builds from this repo.**

## Apps (Coolify project "Target Network")

| App | Env | Branch | Compose file | Domain (on service `edge`) |
|---|---|---|---|---|
| `tn-routing` | production | `staging` (image is branch-independent) | `deploy/coolify/routing.docker-compose.yml` | none (internal) |
| `tn-staging` | staging | `staging` | `deploy/coolify/app.docker-compose.yml` | `staging.targetnetwork.back-on-track.eu` |
| `tn-production` | production | `production` | `deploy/coolify/app.docker-compose.yml` | `targetnetwork.back-on-track.eu` |

Until DNS exists: `staging-targetnetwork.95.216.39.96.sslip.io` / `targetnetwork.95.216.39.96.sslip.io`.

Auto-deploy: push to `staging` → `tn-staging` redeploys; push to `production` → `tn-production`.
The GitHub App `coolify-bot-tn` (org Back-on-Track-eu) delivers the webhooks. This replaces the
bot-server forced-command key (`/opt/tn-deploy/dispatch.sh`).

## One-time on the box

```bash
docker network create tn-shared          # routing engines ⇄ app envs
```

Pre-seed the graph caches instead of waiting for the Drive download (≈1.3 GB each):
```bash
# on bot-server → tn-server (run from an operator machine with both aliases)
ssh bot-server 'docker run --rm -v targetnetwork_tn_graphcache:/g alpine tar cz -C /g .' \
  | ssh tn-server 'docker volume create tn_graphcache_2026 >/dev/null && docker run --rm -i -v tn_graphcache_2026:/g alpine tar xz -C /g'
ssh bot-server 'docker run --rm -v targetnetwork_tn_graphcache_2032:/g alpine tar cz -C /g .' \
  | ssh tn-server 'docker volume create tn_graphcache_2032 >/dev/null && docker run --rm -i -v tn_graphcache_2032:/g alpine tar xz -C /g'
```

## First seed of a fresh environment (staging; production is restored from bot-server instead)

The db starts empty (no initdb mounts, see compose comment). Once the app is deployed and `db` is
healthy, from the box (Coolify → app → Terminal, or ssh):
```bash
P=<coolify app uuid>; cd /data/coolify/applications/$P   # Coolify's checkout
docker compose -p $P -f deploy/coolify/app.docker-compose.yml run --rm --no-deps api \
  sh -c "python scripts/export_country_geoms.py && python db/dev/seed.py"
docker compose -p $P -f deploy/coolify/app.docker-compose.yml run --rm migrate python db/migrate.py --baseline
docker compose -p $P -f deploy/coolify/app.docker-compose.yml run --rm migrate python db/migrate.py --check
```
then redeploy so `ontd-bootstrap` and `country-relations` run. Gate codes: copy `admin.access_codes` +
`admin.access_code_redemptions` from bot-server staging (data-only dump) if the same codes must work.

## Environment variables (set in Coolify, never in git)

`tn-staging` / `tn-production`: `ENV_NAME`, `POSTGRES_USER` (`bot_admin`, as on bot-server: `reseed.sh` and David's pgAdmin assume it), `POSTGRES_PASSWORD`, `POSTGRES_DB` (`target_network`),
`JWT_SECRET` (fresh per box: invalidates old gate cookies, harmless), `SMTP_HOST`, `SMTP_PORT`,
`SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (All-Inkl: authenticate against `w020e032.kasserver.com`,
not the vanity host), optional `GUNICORN_WORKERS` (default 4), `GUNICORN_THREADS` (8),
`API_MEM_LIMIT` (4g), `ONTD_*` overrides.
`tn-routing`: optional `ROUTING_2026_JAVA_OPTS`, `ROUTING_2032_JAVA_OPTS`, `*_MEM_LIMIT`, `GRAPH_CACHE_FILE_ID_*`.

## Coolify gotchas that shaped these files

- Build contexts and bind mounts are relative to the **repo root**, not to this directory.
- `container_name` is ignored; cross-app names are **network aliases** on `tn-shared`.
- **Volumes are renamed** to `<app-uuid>_<name>`: the `name:` key AND `external: true` are both ignored (verified deploys #1 and #2, 2026-09-16). Pre-seeded data therefore goes INTO Coolify's own volumes: `docker run --rm -v tn_graphcache_2026:/src:ro -v <app-uuid>_graphcache-2026:/dst alpine sh -c 'rm -rf /dst/* && cp -a /src/. /dst/'`. The Drive zip unpacks into a `graph-cache-infra-2026/` subfolder, so a fresh download never satisfies the entrypoint's root `properties.txt` marker and the engine loops on "OSM file does not exist" (the 14-09 repackaging issue). Until the zip is flat, always pre-seed.
- **File bind mounts become directories** if the path does not exist at deploy time → no `initdb.d` mounts, and the edge Caddyfile is baked into `Dockerfile.edge` instead of mounted.
- Coolify injects empty strings for declared-but-unset variables → every optional variable
  has a `${VAR:-default}`; required secrets use `${VAR:?…}` so a missing secret fails loudly.
- Only `edge` gets a Coolify domain (port 80). Traefik does TLS + host; Caddy inside does the
  gate. Do **not** put domains on `api` or `frontend`, that would bypass the gate.
- One-shots (`migrate`, `ontd-bootstrap`, `country-relations`) exit 0 by design; Coolify shows
  them as exited, that is expected.

## Data migration from bot-server (production cut-over)

`pg_dump` the bot-server production DB → restore into the new `tn-production` db → **setval every
serial sequence** after a COPY-restore (lesson 2026-08-31, redemption ids) → point DNS (Juri, KAS)
→ keep bot-server production read-only for a week, then retire. Staging is reseeded fresh here.

## Database access for developers (SSH tunnel, pgAdmin)

The `db` service publishes Postgres on **localhost only**: `127.0.0.1:${DB_DEBUG_PORT}` on tn-server
(`DB_DEBUG_PORT` is a Coolify environment variable per app: **staging 55433, production 55434**, the
bot-server convention). Nothing is reachable from the internet; the only door is an SSH tunnel through a
restricted user whose key may forward exactly those two ports and nothing else:

```
# ~/.ssh/authorized_keys of user `david` on tn-server
restrict,port-forwarding,permitopen="127.0.0.1:55433",permitopen="127.0.0.1:55434" ssh-ed25519 AAAA… davidj.wedekind@gmail.com
```

Desktop side (pgAdmin, DBeaver, psql):

```
ssh -N -L 55433:127.0.0.1:55433 -L 55434:127.0.0.1:55434 david@95.216.39.96
# then connect to localhost:55433 (staging) / localhost:55434 (production), db target_network
```

Roles: `david` exists in both databases. Staging: read + write on every application schema (it is the
test bench). Production: **read-only** (`SELECT` on all schemas, `pg_read_all_data`); writes go through
the app or a reviewed migration. Passwords live in Gio's bws (`TN_PG_DAVID_STAGING`, `TN_PG_DAVID_PRODUCTION`)
and are shared once via Bitwarden Send. Roles are not part of `pg_dump` (`--no-owner --no-acl`): after any
copy or reseed, re-run the grants (`deploy/coolify/grants-david.sql`).
