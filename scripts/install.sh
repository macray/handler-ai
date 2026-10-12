#!/bin/sh
# Install handler for people without uv (README "Install"); with uv, `uv tool install handler-ai`
# does the same. Attached to each release:
#
#   curl -fsSL https://github.com/macray/handler-ai/releases/latest/download/install.sh | sh
#   HANDLER_WHEEL=dist/handler_ai-0.1.0-py3-none-any.whl sh scripts/install.sh  (a wheel you built)
#
# Installs uv if it is missing (https://astral.sh/uv), then handler-ai from PyPI as a uv tool:
# `handler` (also as `handler-ai`), `handlerd`, `handler-harness` and `handler-sandbox-podman` in
# ~/.local/bin, Python fetched by uv if needed. Changes nothing else: `handler setup` then starts
# handlerd and checks this machine. `uv tool upgrade handler-ai` updates it.
set -eu

PACKAGE="${HANDLER_WHEEL:-handler-ai}"

say() { printf '%s\n' "$*"; }
fail() { say "handler install: $*" >&2; exit 1; }

[ "$(uname -s)" = Linux ] || fail "handler runs on Linux only (for now)"

if ! command -v podman >/dev/null 2>&1; then
    id=$(. /etc/os-release 2>/dev/null && printf '%s' "${ID:-}")
    case "$id" in
        arch|manjaro|endeavouros) hint="sudo pacman -S podman passt" ;;
        debian|ubuntu|linuxmint|pop) hint="sudo apt install podman passt" ;;
        fedora|rhel|centos|rocky|almalinux) hint="sudo dnf install podman passt" ;;
        opensuse*|sles) hint="sudo zypper install podman passt" ;;
        *) hint="install podman and passt with your package manager" ;;
    esac
    say "podman is not installed: handler runs its agents in podman containers. Install it ($hint);"
    say "the installation goes on, \`handler setup\` checks it afterwards."
fi

if ! command -v uv >/dev/null 2>&1; then
    say "Installing uv (https://astral.sh/uv), which installs and updates handler…"
    command -v curl >/dev/null 2>&1 || fail "curl is needed to install uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$HOME/.local/bin:$PATH"
    command -v uv >/dev/null 2>&1 || fail "uv was installed but is not on PATH: open a new shell"
fi

say "Installing handler…"
uv tool install --force --python '>=3.12' "$PACKAGE"

bin=$(uv tool dir --bin)
case ":$PATH:" in
    *":$bin:"*) ;;
    *) say "Add $bin to your PATH (\`uv tool update-shell\` does it), then open a new shell." ;;
esac
say ""
say "handler is installed. Next: handler setup"
