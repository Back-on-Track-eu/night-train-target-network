# Deploy handover — notes from the backend side

David → Giovanni, 2026-08-10. Written from a full snapshot audit of
environment variables and ports across the repo. Nothing in `deploy/` has
been changed except two comment lines in `bot-server-app/local.sh` (see §4)
— everything else here is findings and one incoming change, for you to
action or discard as you see fit.

---

## 1. How deploy relates to the backend `.env` (context, no action)

`deploy/bot-server-app/docker-compose.yml` enumerates every variable the
`api` service needs in its own `environment:` block. It does **not** use
`env_file:`, and it does not read `backend/docker/.env`.

That separation is deliberate and I'd keep it: `backend/docker/.env.example`
carries working *dev defaults* (`POSTGRES_PASSWORD=devpassword`,
`AUTH_EMAIL_DEV_MODE`, a Drive graph-cache id), and CI copies it verbatim.
None of that belongs on a server. The rule is now written down in AGENTS.md
("Parameter placement"): one dev-side `.env`; server stacks enumerate their
environment explicitly.

The trade-off is that a variable added on the backend side is silently
absent on staging/production until someone adds it to your `environment:`
block. I checked every one currently unset — none break a boot or a request
path today (they all have code defaults, and the ONTD ones are moot because
of §3 below). So there is nothing to backfill right now. This is just the
mechanism to know about when reviewing future backend PRs.

If you'd rather not track it by hand, the alternative is a small
`deploy/bot-server-app/.env.defaults` committed to git (non-secret
operational values only) listed *before* `.env` in an `env_file:` array
(last file wins), with the secret ones staying in `.env`. Your call — I'm
not proposing it, just noting it exists.

## 2. `LOCAL_HTTP_PORT` is missing from `.env.example`

`docker-compose.local.yml` reads `${LOCAL_HTTP_PORT:-8090}` for the local
Caddy's published port, but `deploy/bot-server-app/.env.example` doesn't
mention it. `local.sh` generates `.env` from that file, so anyone whose 8090
is taken has to discover the variable by reading the compose file.

Suggested addition to `deploy/bot-server-app/.env.example`, next to
`API_DEBUG_PORT` / `DB_DEBUG_PORT`:

```bash
# Local-only: the port docker-compose.local.yml's Caddy publishes. Ignored on
# the server, where Caddy is the shared nextcloud vhost. Override if 8090 is
# taken on your machine.
LOCAL_HTTP_PORT=8090
```

## 3. ONTD reference data never loads on staging/production

`backend/docker/entrypoint.sh` runs `seed.py`, then `db/ontd/bootstrap.py`
in the background, then gunicorn. Your `api` service overrides it with an
explicit `command: [gunicorn, ...]` — correctly, since the entrypoint's
`seed.py` starts with `DROP SCHEMA … CASCADE` and must never run on a
long-lived database.

The side effect is that `bootstrap.py` doesn't run either, so
`ontd.route_summaries` stays empty and the gallery shows proposals only —
no existing-night-train context.

If that's intentional, ignore this. If the servers should show existing
routes, it needs its own one-shot invocation (same shape as `migrate`), plus
`ONTD_WORKBOOK_ID` / `ONTD_COMPOSITIONS_ID` in the `environment:` block. The
routing engine has to be reachable for it, and it re-routes ~205 routes, so
it is not a per-deploy step — more like a manual `docker compose run --rm`
after a schema reset. CI does exactly that shape:
`bootstrap.py --force --strict`.

## 4. `local.sh` header comments said port 8080

Fixed in this batch (the one deploy-side change, per David): two comment
lines in `deploy/bot-server-app/local.sh` claimed `http://localhost:8080`
while the default is 8090 (`docker-compose.local.yml` and the README table
were already right). Comment-only, no behaviour change.

## 5. Incoming backend change: ports moved into `.env` (this batch)

Background: when we shifted the API host port for Bjarne, the change had to
be made in ~15 places because ports were hardcoded in compose files, tests,
scripts and the Vite config. Fixed on the backend side — every port is now
an `.env` variable with the current value as its default, so behaviour is
unchanged but a future switch is a one-line edit.

New variables in `backend/docker/.env` (dev side only — these do **not**
propagate to your stacks): `API_HOST_PORT` (5050), `API_CONTAINER_PORT`
(5000), `POSTGRES_HOST_PORT` (5432), `OPENRAILROUTING_ADMIN_HOST_PORT`
(8990), `FRONTEND_HOST_PORT`/`FRONTEND_CONTAINER_PORT` (5173),
`MATHESAR_HOST_PORT` (8000).

**What touches you:** only `API_CONTAINER_PORT`. The shared image's
`backend/docker/entrypoint.sh` now binds gunicorn to
`0.0.0.0:${API_CONTAINER_PORT:-5000}` — but your stacks override the
entrypoint with their own `command:`, and never set that variable, so
nothing changes for you. Flagging it only so that if you ever want to move
the container-side port, these are the places that hold `5000` in your
compose and must move together: the `--bind` in your `command:`, the
`ports:` mapping, and the healthcheck URL.

Host-side deploy ports (`API_DEBUG_PORT`, `DB_DEBUG_PORT`,
`LOCAL_HTTP_PORT`) stay entirely yours — naming untouched.

## 6. Two legacy deploy directories

Both predate `bot-server-app` and, as far as I can tell from the snapshot,
neither can boot against current `main`:

**`deploy/bot-server/`** (the June-23 production stack)
- `openrailrouting` build context points at
  `../../backend/models/route_evaluation_model/routing/docker`, a path that
  no longer exists — it's `backend/models/route/routing/docker` now.
- The `api` service passes no `JWT_SECRET`. `api/auth_utils.py`'s
  `check_auth_config()` runs at boot from `main.py` and raises without one,
  so the container would exit on start.

**`deploy/bot-server-demo/`**
- Same missing `JWT_SECRET` → same boot failure.
- Its README describes the DB schema as frozen at 23-Jun vintage (no
  `scenario` schema), so it predates several schema generations.

My read is these should be deleted rather than repaired, now that
`bot-server-app` covers staging and production from one parameterized file.
But that's a call for you — if either is still serving something on the
box, say so and I'll leave them in the docs.

---

## Questions back to me

- Should ONTD load on staging/production (§3)?
- Retire `bot-server/` and `bot-server-demo/` (§6)?
