#!/usr/bin/env bash
# =============================================================================
# Forced-command dispatcher for the GitHub Actions deploy key.
#
# The deploy key in root's authorized_keys is locked to this script:
#
#   command="/opt/tn-deploy/dispatch.sh",restrict ssh-ed25519 AAAA... tn-deploy
#
# so a leaked key can trigger a deploy of one of the two environments and
# NOTHING else — no shell, no port forwarding, no arbitrary commands.
# Install: copy this file to /opt/tn-deploy/dispatch.sh (chmod 755) — it is
# referenced by absolute path from authorized_keys, independent of checkouts.
# =============================================================================
set -euo pipefail

case "${SSH_ORIGINAL_COMMAND:-}" in
    staging)
        exec /opt/targetnetwork-staging/deploy/bot-server-app/deploy.sh
        ;;
    production)
        exec /opt/targetnetwork-production/deploy/bot-server-app/deploy.sh
        ;;
    *)
        echo "dispatch: unknown deploy target '${SSH_ORIGINAL_COMMAND:-}' (want: staging|production)" >&2
        exit 64
        ;;
esac
