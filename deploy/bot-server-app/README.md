# Target Network — staging + production on bot-server

One parameterized compose stack (`docker-compose.yml` here) runs **both**
server environments from two branch-pinned checkouts:

| | staging | production |
|---|---|---|
| Checkout | `/opt/targetnetwork-staging` | `/opt/targetnetwork-production` |
| Branch | `staging` | `production` |
| URL | `https://targetnetwork.65.109.137.97.sslip.io` (basic-auth) | `https://targetnetwork.back-on-track.eu` |
| Containers | `tn-staging-db/-migrate/-api/-frontend` | `tn-production-db/-migrate/-api/-frontend` |
| Debug binds (localhost) | api `5056`, db `55433` | api `5057`, db `55434` |
| DB volume | `tn_staging_pgdata` | `tn_production_pgdata` |

Merged PR → branch push → GitHub Actions (`deploy-staging.yml` /
`deploy-production.yml`) → SSH forced-command → `deploy.sh`:
fast-forward pull → build → **migrations applied before the api may start**
→ `migrate.py --check` assertion → health check. A failed deploy is a red X
on the commit.

Both environments share the existing `targetnetwork-routing` engine
(stateless per request; the ~840 MiB JVM doesn't fit on this box twice) by
joining its `targetnetwork_default` network. **Do not restart it casually**
— the rail graph takes ~2 min to reload.

## First-time setup of an environment

```bash
# as root on bot-server — example: staging
git clone git@github.com:Back-on-Track-eu/night-train-target-network.git \
    /opt/targetnetwork-staging          # uses the repo deploy key
cd /opt/targetnetwork-staging && git checkout staging
cd deploy/bot-server-app
cp .env.example .env && vim .env        # fill; chmod 600 .env

docker compose up -d db                 # initdb runs create_*.sql = latest state
docker compose run --rm migrate python db/migrate.py --baseline
                                        # DB born at latest state: record all
                                        # migrations as applied, execute nothing
docker compose run --rm api python db/dev/seed.py   # one-time seed (params + demo data)
docker compose up -d --build
```

After first-time setup, never run seed.py or `--baseline` on the environment
again — `deploy.sh` and the `migrate` service handle everything from here.

## Deploy key + forced command (one-time server setup)

1. `ssh-keygen -t ed25519 -f /root/.ssh/tn_repo_deploy -C tn-repo-read` →
   add the public key as a **read-only deploy key** on the GitHub repo
   (both checkouts pull with it via `core.sshCommand` or default identity).
2. `ssh-keygen -t ed25519 -f tn_actions_deploy -C tn-actions` → private key
   into the repo secret `TN_DEPLOY_SSH_KEY`; public key into
   `/root/.ssh/authorized_keys` as:
   ```
   command="/opt/tn-deploy/dispatch.sh",restrict ssh-ed25519 AAAA... tn-actions
   ```
3. `mkdir -p /opt/tn-deploy && cp deploy/bot-server-app/dispatch.sh /opt/tn-deploy/ && chmod 755 /opt/tn-deploy/dispatch.sh`

The Actions key can say `staging` or `production` to this box and nothing
else — no shell, no forwarding (`restrict`).

## Caddy vhosts

```
# staging — keep basic-auth until the GDPR gate clears
targetnetwork.65.109.137.97.sslip.io {
    basic_auth {
        volunteer <bcrypt-hash>   # rotate ≤ 2026-08-18: old creds leaked in board minutes
    }
    handle /api/* {
        reverse_proxy tn-staging-api:5000
    }
    handle {
        reverse_proxy tn-staging-frontend:80
    }
    header -Server
}

# production
targetnetwork.back-on-track.eu {
    handle /api/* {
        reverse_proxy tn-production-api:5000
    }
    handle {
        reverse_proxy tn-production-frontend:80
    }
    header -Server
}
```

Caddy runs in the nextcloud stack; after editing its Caddyfile use
`docker exec nextcloud-caddy-1 caddy reload --config /etc/caddy/Caddyfile`
(never regex-edit the Caddyfile — append blocks, keep a `.bak`).

## Desktop pgAdmin access (per-person DB users)

The db containers bind to localhost only. From a desktop:

```bash
ssh -N -L 55433:127.0.0.1:55433 root@cloud.back-on-track.eu   # staging
ssh -N -L 55434:127.0.0.1:55434 root@cloud.back-on-track.eu   # production
```

then point pgAdmin at `127.0.0.1:55433/55434` with your personal DB user
(not `bot_admin` — per-person users exist so changes are traceable).

## Transition from the pre-2026-07-23 layout (one-time, done ≈ 2026-07-28)

The 23-jun frozen stack (`night-train-api`, old `targetnetwork-db`) is
stopped — not removed — after a final dump to `/opt/targetnetwork/backups/`
(nightly restic ships it offsite). `targetnetwork-routing` from that compose
stays up as the shared engine. The demo stack (`tn-demo-*`,
`/opt/targetnetwork-demo`) is replaced by the staging environment and its
vhost `targetnetwork-demo.…sslip.io` removed.
