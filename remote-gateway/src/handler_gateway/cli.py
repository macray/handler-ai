"""handler-gateway — run the gateway, and manage the hosts allowed to use it.

    handler-gateway serve [--host 127.0.0.1] [--port 7431] [--client DIR]
    handler-gateway add-host NAME   prints the host token (give it to handler: Settings → Remote)
    handler-gateway hosts           hosts and how many devices each registered
    handler-gateway remove-host ID  the host and its devices

State: $HANDLER_GATEWAY_STATE (default ~/.local/state/handler-gateway/state.json), and next to it
state.queue.json (what devices queued for when their host is back).
Client: --client or $HANDLER_GATEWAY_CLIENT_DIR, the built remote client served at / (optional).
Serve it over HTTPS (reverse proxy, `tailscale serve`): browsers only give the client its
cryptography (WebCrypto) on https:// pages or localhost.
"""

import argparse
import os
import sys
from pathlib import Path

import uvicorn

from .app import Limits, State, create_app
from .store import Queue, Registry


def state_path() -> Path:
    default = Path.home() / ".local" / "state" / "handler-gateway" / "state.json"
    return Path(os.environ.get("HANDLER_GATEWAY_STATE", default))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="handler-gateway", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the gateway")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7431)
    serve.add_argument("--client", default=os.environ.get("HANDLER_GATEWAY_CLIENT_DIR"))
    add = sub.add_parser("add-host", help="allow a new host; prints its token")
    add.add_argument("name")
    sub.add_parser("hosts", help="list hosts")
    remove = sub.add_parser("remove-host", help="remove a host and its devices")
    remove.add_argument("id")
    args = parser.parse_args(argv)

    registry = Registry(state_path())
    if args.command == "add-host":
        token = registry.add_host(args.name)
        print(token)
        print(f"host {token.split('.')[0]} added; this token is shown once", file=sys.stderr)
        return 0
    if args.command == "hosts":
        for host_id, host in sorted(registry.hosts.items()):
            print(f"{host_id}  {host['name']}  devices: {len(registry.devices_of(host_id))}")
        return 0
    if args.command == "remove-host":
        if not registry.remove_host(args.id):
            print(f"no host {args.id}", file=sys.stderr)
            return 1
        return 0

    client = Path(args.client) if args.client else None
    queue = Queue(state_path().with_name(state_path().stem + ".queue.json"))
    app = create_app(State(registry, Limits(), queue=queue), client)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        proxy_headers=True,
        log_level="info",
        timeout_graceful_shutdown=3,  # long polls would hold a shutdown for 25 s
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
