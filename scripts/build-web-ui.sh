#!/usr/bin/env bash
# Build the web apps (one bun workspace, package.json at the repository root):
#   packages/control-plane/src/handler_control/web-ui  the handler web UI, served by handlerd at / (and
#                                in the wheel, packaging/)
#   packages/remote-client/dist  the remote client, served by the gateway (remote-gateway/)
# Both use packages/acp-view (session rendering, compiled by each app).
# Uses bun if installed on the host, otherwise Bun's image, at the version apps run on
# (RUNTIME_VERSION, handler_contracts/app.py): no Node/Bun needed on the host.
#
#   scripts/build-web-ui.sh           install (frozen lockfile), generate types, check, test, build
#   scripts/build-web-ui.sh --quick   install + build only
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"

steps='bun install --frozen-lockfile && bun run gen:types'
if [ "${1:-}" != "--quick" ]; then
    steps="$steps && (cd packages/acp-view && bun run check)"
    steps="$steps && (cd packages/web-ui && bun run check && bun run test)"
    steps="$steps && (cd packages/remote-client && bun run check && bun run test)"
fi
steps="$steps && (cd packages/web-ui && bun run build) && (cd packages/remote-client && bun run build)"

if command -v bun >/dev/null; then
    bash -c "$steps"
else
    version="$(sed -n 's/^RUNTIME_VERSION = "\(.*\)"$/\1/p' packages/contracts/src/handler_contracts/app.py)"
    image="docker.io/oven/bun:${version:?RUNTIME_VERSION not found}"
    podman run --rm --userns=keep-id --user "$(id -u):$(id -g)" -e HOME=/tmp \
        -v "$repo:$repo" -w "$repo" "$image" bash -c "$steps"
fi
echo "web UI built: $repo/packages/control-plane/src/handler_control/web-ui"
echo "remote client built: $repo/packages/remote-client/dist"
