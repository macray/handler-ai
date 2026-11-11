"""Secret store routes: values written and deleted, never read back (D.14)."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response
from pydantic import TypeAdapter, ValidationError

from handler_contracts import (
    CommandSecret,
    PutSecretRequest,
    SecretInfo,
    SecretPath,
    SecretRef,
    SecretSent,
    egress_target,
)
from handler_harness import catalog

from .. import (
    accounts,
    bindings,
    providers,
    secrets,
)
from .accounts import ad_hoc_label, references
from .common import Context, ProblemError, dump, log, parse_body


def add_secret_routes(app: FastAPI, ctx: Context) -> None:
    """D.14: values are written, described and deleted here, never read back."""
    authed = [Depends(ctx.require_auth)]
    store = secrets.SecretStore(ctx.settings.data_dir)

    @app.get("/v1/secrets", dependencies=authed)
    def list_secrets() -> Response:
        return dump(secret_infos(ctx, store))

    @app.put("/v1/secrets/{path:path}", dependencies=authed)
    async def put_secret(path: str, request: Request) -> Response:
        path = secret_path(path)
        if path.startswith("apps/"):
            raise ProblemError(
                409, "an app's secrets are set on the app", "/v1/apps/{name}/secrets"
            )
        if path.startswith("accounts/"):
            raise ProblemError(409, "an account's login is set on it", "/v1/accounts/{name}/login")
        body = parse_body(PutSecretRequest, await request.body())
        store.put(path, body.value, body.description)
        log.info("secret %s set", path)
        return dump(next(s for s in secret_infos(ctx, store) if s.path == path))

    @app.delete("/v1/secrets/{path:path}", dependencies=authed)
    def delete_secret(path: str) -> Response:
        """`path` and everything under it; refused while one of them is referenced."""
        path = secret_path(path)
        within = [
            s for s in secret_infos(ctx, store) if s.path == path or s.path.startswith(path + "/")
        ]
        if users := sorted({u for s in within for u in s.used_by}):
            raise ProblemError(409, "secret in use", ", ".join(users))
        if not store.delete(path):
            raise ProblemError(404, "no such secret", path)
        log.info("secret %s deleted", path)
        return Response(status_code=204)


_SECRET_PATH = TypeAdapter(SecretPath)


def secret_path(path: str) -> str:
    try:
        return _SECRET_PATH.validate_python(path)
    except ValidationError:
        raise ProblemError(400, "invalid secret path", path) from None


def secret_infos(ctx: Context, store: secrets.SecretStore) -> list[SecretInfo]:
    """Every secret handler uses, by path: those its store holds and those the accounts, providers
    and bindings reference elsewhere (each under the path it would have in the store), with what
    they belong to, the agents whose sandboxes get them, and how (E3: the hosts their proxies give
    them to, or why the process gets the value itself). An app's secrets reach its backend as
    environment variables (H.2)."""
    settings = ctx.settings
    rows: dict[str, SecretInfo] = {s.path: s for s in store.list()}
    users = references(ctx)

    def add(
        owner: str, path: str, ref: SecretRef, hosts: list[str] | None, agents: list[str]
    ) -> None:
        value = _value(ref, store)
        row = rows.get(path) or SecretInfo(path=path, source=secrets.kind(ref))
        rows[path] = row.model_copy(
            update={
                "has_value": isinstance(ref, CommandSecret) or value is not None,
                "used_by": sorted({*row.used_by, owner}),
                "agents": sorted({*row.agents, *agents}),
                "hosts": sorted({*row.hosts, *(hosts or [])}),
                "visible": row.visible or secrets.visible(value, hosts),
            }
        )

    for a in accounts.load_all(settings.accounts_dir):
        if a.account is not None and a.account.token is not None:
            hosts = _login_hosts(a.account.harness)
            path = secrets.name_of(a.account.token, accounts.token_path(a.name))
            add(
                f"accounts/{a.name}", path, a.account.token, hosts, users["account"].get(a.name, [])
            )
    for p in providers.load_all(settings.providers_dir):
        if p.provider is not None and p.provider.api_key is not None:
            hosts = sorted({egress_target(url) for url in p.provider.endpoints.values()})
            path = secrets.name_of(p.provider.api_key, providers.key_path(p.name))
            add(
                f"providers/{p.name}",
                path,
                p.provider.api_key,
                hosts,
                users["provider"].get(p.name, []),
            )
    picked = binding_agents(ctx)
    for b in bindings.load_all(settings.bindings_dir):
        if b.binding is None or b.addon is None:
            continue
        for slot, ref in (b.binding.secrets or {}).items():
            hosts = b.addon.manifest.secret_hosts(slot)
            path = secrets.name_of(ref, bindings.secret_path(b.name, slot))
            add(f"connections/{b.name}", path, ref, hosts, picked.get(b.name, []))
    for name in ctx.apps.records:
        for secret in ctx.apps.declared_secrets(name):
            path = f"apps/{name}/{secret}"
            row = rows.get(path) or SecretInfo(path=path, has_value=False)
            rows[path] = row.model_copy(
                update={
                    "used_by": [f"apps/{name}"],
                    "visible": "an app's backend gets it as an environment variable (H.2)",
                }
            )
    sent = _last_sent(ctx)
    return [r.model_copy(update={"last_sent": sent.get(p)}) for p, r in sorted(rows.items())]


def binding_agents(ctx: Context) -> dict[str, list[str]]:
    """The agents using each binding (theirs or their project's), labelled as `references` labels
    them."""
    found: dict[str, list[str]] = {}
    for record in ctx.registry.agents.values():
        label = ctx.projects.label(record) if record.project_id else ad_hoc_label(record)
        for name in (u.binding for u in record.addon_uses if u.binding is not None):
            found.setdefault(name, []).append(label or record.id)
    return found


def _value(ref: SecretRef, store: secrets.SecretStore) -> str | None:
    """Its value when it has one, never a command's (not run to describe it)."""
    if isinstance(ref, CommandSecret):
        return None
    try:
        return secrets.resolve(ref, store)
    except secrets.SecretError:
        return None


def _login_hosts(harness: str) -> list[str]:
    try:
        login = catalog.get(harness).descriptor.login
    except catalog.UnknownHarnessError:
        return []
    return list(login.hosts) if login is not None else []


def _last_sent(ctx: Context) -> dict[str, SecretSent]:
    """The latest `injected` event of each secret in the agents' recent events (A.3)."""
    found: dict[str, SecretSent] = {}
    for record in ctx.registry.agents.values():
        for e in record.events:
            name = e.get("secret") if e.get("decision") == "injected" else None
            if name and (name not in found or found[name].t < e["t"]):
                found[name] = SecretSent(t=e["t"], host=e["host"])
    return found
