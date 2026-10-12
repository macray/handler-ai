#!/usr/bin/env bash
# Build the `handler-ai` wheel users install (packaging/): the web UI first (it is shipped inside), then
# the wheel, into dist/ (or $1). Prints the wheel's path last.
#
#   scripts/build-wheel.sh [OUT_DIR]
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="$(realpath -m "${1:-$repo/dist}")"
cd "$repo"

scripts/build-web-ui.sh --quick >&2
test -f packages/control-plane/src/handler_control/web-ui/index.html \
    || { echo "the web UI was not built" >&2; exit 1; }
rm -f "$out"/handler_ai-*.whl
uv build --wheel packaging --out-dir "$out" >&2
ls "$out"/handler_ai-*.whl
