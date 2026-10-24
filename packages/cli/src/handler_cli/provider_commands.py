"""`handler provider …` — providers (contract D.12): where model calls go when no subscription
does, an API and its key (Anthropic, OpenAI, Mistral, OpenRouter) or a model server on this
computer (llama.cpp, Ollama). A provider starts from a template; its key goes to handler's secret
store, never shown again.

handler provider list                the providers: endpoints, models, key, areas, agents
handler provider templates           what a provider can start from
handler provider add NAME --from TEMPLATE [--key] [--endpoint PROTOCOL=URL …] [--model ID …]
                     [--area AREA …] [--description TEXT]
                                     a provider from a template. --key: ask for its key (hidden,
                                     or read from stdin). --endpoint: another URL for a protocol
                                     (e.g. a server on another port). --model: the models it offers,
                                     instead of the template's. --area: the areas it
                                     is made for (Work, Personal…, or any; none: it runs nowhere a
                                     project has an area)
handler provider rm NAME             it and its key (agents using it cannot start until given
                                     another)

Models' details and per-harness files are edited in the web UI (Settings → Model access) or in
~/.config/handler-ai/providers/NAME.toml.
"""

import argparse
from typing import Any

from .account_commands import ask_token
from .client import ClientError, Daemon
from .output import table


def add_parser(sub: Any) -> None:
    provider = sub.add_parser("provider", help="providers", description=__doc__,
                              formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    p = provider.add_subparsers(dest="provider_cmd", required=True)
    p.add_parser("list")
    p.add_parser("templates")
    add = p.add_parser("add")
    add.add_argument("name")
    add.add_argument("--from", dest="template", required=True, metavar="TEMPLATE")
    add.add_argument("--key", action="store_true", help="ask for its key")
    add.add_argument("--endpoint", action="append", metavar="PROTOCOL=URL", default=[])
    add.add_argument("--model", action="append", metavar="ID", default=[])
    add.add_argument("--area", action="append", metavar="AREA", default=[])
    add.add_argument("--description")
    p.add_parser("rm").add_argument("name")


def dispatch(args: argparse.Namespace) -> int:
    d = Daemon()
    if args.provider_cmd == "list":
        rows = [["NAME", "STATUS", "ENDPOINTS", "MODELS", "KEY", "AREAS", "AGENTS"]]
        for p in d.call("GET", "/v1/providers"):
            status = p["status"] if p["status"] == "ready" else "; ".join(
                p.get("problems") or [p.get("error") or p["status"]])  # fmt: skip
            rows.append(
                [
                    p["name"],
                    status,
                    ", ".join(p.get("endpoints", {})),
                    ", ".join(m["id"] for m in p.get("models", [])),
                    p.get("key") or "-",
                    ", ".join(p.get("areas", [])) or "-",
                    ", ".join(p.get("agents", [])) or "-",
                ]
            )
        table(rows) if len(rows) > 1 else print("no provider: handler provider templates")
    elif args.provider_cmd == "templates":
        rows = [["TEMPLATE", "KEY", "ENDPOINTS", "DESCRIPTION"]]
        for t in d.call("GET", "/v1/provider-templates"):
            needs = "needed" if t.get("needsKey") else "-"
            endpoints = ", ".join(f"{k} {v}" for k, v in t["endpoints"].items())
            rows.append([t["name"], needs, endpoints, t.get("description") or ""])
        table(rows)
    elif args.provider_cmd == "add":
        made = d.call("POST", "/v1/providers", request(d, args))
        print(f"{made['name']}: created ({made['status']})")
    else:
        d.call("DELETE", f"/v1/providers/{args.name}")
        print(f"{args.name}: removed")
    return 0


def request(d: Daemon, args: argparse.Namespace) -> dict[str, Any]:
    """`POST /v1/providers`'s body: the template, changed by the flags typed (as the web UI's form
    starting from it)."""
    templates = d.call("GET", "/v1/provider-templates")
    template = next((t for t in templates if t["name"] == args.template), None)
    if template is None:
        names = ", ".join(t["name"] for t in templates)
        raise ClientError(f"no template '{args.template}': {names}")
    endpoints = dict(template["endpoints"])
    for given in args.endpoint:
        protocol, _, url = given.partition("=")
        if not url:
            raise ClientError(f"--endpoint {given}: PROTOCOL=URL, e.g. openai-chat=http://…")
        endpoints[protocol] = url
    models = template["models"]
    if args.model:
        known = {m["id"]: m for m in models}
        models = [known.get(model, {"id": model}) for model in args.model]
    body: dict[str, Any] = {
        "name": args.name,
        "description": args.description or template.get("description"),
        "endpoints": endpoints,
        "models": models,
        "areas": args.area,
        "files": template.get("files"),
    }
    if args.key:
        body["key"] = ask_token(args.name, "key")
    elif template.get("needsKey"):
        raise ClientError(f"{args.template} needs a key: add --key")
    return body
