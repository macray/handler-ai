#!/usr/bin/env bash
# Install the wheel as a user would (scripts/install.sh) in a bare Debian container with no
# checkout, then check what an installed handler must do without podman or systemd: every command
# runs, handlerd starts, serves the web UI and the API, copies the default toolbox to the user's
# folder, and `handler setup` stops with its reasons. Needs the internet (uv, Python, dependencies).
#
#   scripts/smoke-install.sh [WHEEL]     default: build it (scripts/build-wheel.sh)
#   CONTAINER=docker scripts/smoke-install.sh …   (default: podman)
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
engine="${CONTAINER:-podman}"
wheel="${1:-$("$repo/scripts/build-wheel.sh" | tail -1)}"
wheel="$(realpath "$wheel")"

"$engine" run --rm -i \
    -v "$wheel:/wheel/$(basename "$wheel"):ro" -v "$repo/scripts/install.sh:/install.sh:ro" \
    docker.io/library/debian:stable-slim bash -s "/wheel/$(basename "$wheel")" <<'EOF'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null
useradd -m user
cp "$1" /home/user/ && chown user /home/user/*.whl
su - user -c "HANDLER_WHEEL=/home/user/$(basename "$1") sh /install.sh"
su - user -s /bin/bash <<'USER'
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
ok() {  # ok WHAT COMMAND…: a failed check stops the smoke test
    local what="$1"; shift
    if "$@"; then printf 'smoke: %s\n' "$what"; else printf 'smoke FAILED: %s\n' "$what"; exit 1; fi
}
ok "handler" bash -c "handler --help >/dev/null"
ok "handler-harness: the packaged harnesses" grep -q claude-code <(handler-harness list)
ok "handler-sandbox-podman" bash -c "handler-sandbox-podman --help >/dev/null"
handlerd >handlerd.log 2>&1 &
for _ in $(seq 60); do curl -fs http://127.0.0.1:7430/v1/health >/dev/null && break; sleep 1; done
ok "handlerd answers" grep -q '"status":"ok"' <(curl -fs http://127.0.0.1:7430/v1/health)
ok "the web UI is served" grep -qi '<!doctype html' <(curl -fs http://127.0.0.1:7430/)
token="$(cat ~/.config/handler-ai/token)"
api() { curl -fs -H "Authorization: Bearer $token" "http://127.0.0.1:7430$1"; }
ok "the API lists the harnesses" grep -q '"claude-code"' <(api /v1/harnesses)
ok "the built-in tools" grep -q '"builtin":true' <(api /v1/addons)
ok "the official source is listed" grep -q '"official":true' <(api /v1/sources)
ok "the runtime check sees no podman" grep -q '"ok":false' <(api /v1/runtime)
ok "the default toolbox, copied to the user's" test -f ~/.config/handler-ai/toolbox/Containerfile
ok "the toolbox editor reads it" grep -q 'handler toolbox' <(api /v1/toolbox/containerfile)
ok "the provider templates" grep -q 'anthropic-api' <(api /v1/provider-templates)
ok "handler setup fails without systemd" bash -c '! handler setup --no-build >setup.log 2>&1'
ok "… saying why" grep -q 'run `handlerd` yourself' setup.log
USER
echo "smoke: all good"
EOF
