"""Account routes: accounts and their login (D.9)."""

from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response

from handler_contracts import (
    AccountInfo,
    AccountLoginRequest,
    AccountRequest,
    LoginWindow,
)

from .. import (
    accounts,
    secrets,
    terminal,
)
from ..agents import AgentRecord
from ..settings import Settings
from .areas import check_areas
from .common import Context, ProblemError, dump, log, parse_body


def add_account_routes(app: FastAPI, ctx: Context) -> None:
    """D.9: an account is its harness, a description, its plan and its login."""
    authed = [Depends(ctx.require_auth)]
    settings = ctx.settings
    store = secrets.SecretStore(settings.data_dir)
    credentials = settings.data_dir / "accounts"

    @app.get("/v1/accounts", dependencies=authed)
    def list_accounts() -> Response:
        return dump(account_infos(ctx))

    @app.post("/v1/accounts", dependencies=authed)
    async def create_account(request: Request) -> Response:
        body = parse_body(AccountRequest, await request.body())
        check_areas(ctx, body.areas)
        try:
            accounts.create(
                settings.accounts_dir,
                body.name,
                body.harness,
                body.description,
                plan=body.plan,
                connectors=body.connectors,
                areas=body.areas,
            )
        except accounts.AccountError as e:
            raise ProblemError(409, "cannot create the account", str(e)) from None
        log.info("account %s created (%s)", body.name, body.harness)
        return dump(account_info(ctx, body.name), status=201)

    @app.put("/v1/accounts/{name}", dependencies=authed)
    async def update_account(name: str, request: Request) -> Response:
        """Its description, plan, connectors and areas, and its name while no agent uses it.
        Not its harness."""
        body = parse_body(AccountRequest, await request.body())
        check_areas(ctx, body.areas)
        old = account_or_404(settings, name)
        if old.account is None:
            raise ProblemError(409, "invalid account: fix its file", old.error)
        if body.harness != old.account.harness:
            raise ProblemError(409, "an account's harness cannot change", old.account.harness)
        if body.name != name and (users := references(ctx)["account"].get(name)):
            raise ProblemError(409, "account in use: cannot rename it", ", ".join(users))
        try:
            accounts.update(
                settings.accounts_dir,
                credentials,
                store,
                old,
                name=body.name,
                description=body.description,
                plan=body.plan,
                connectors=body.connectors,
                areas=body.areas,
            )
        except accounts.AccountError as e:
            raise ProblemError(409, "cannot change the account", str(e)) from None
        return dump(account_info(ctx, body.name))

    @app.delete("/v1/accounts/{name}", dependencies=authed)
    def delete_account(name: str) -> Response:
        """It and its login. The agents using it keep its name, a model that cannot start
        until they are given another account (E1)."""
        account_or_404(settings, name)
        accounts.delete(settings.accounts_dir, credentials, store, name)
        log.info("account %s deleted", name)
        return Response(status_code=204)


def add_account_login_routes(app: FastAPI, ctx: Context) -> None:
    """D.9: an account's login: a token the person gives, or the file a login handler runs left."""
    authed = [Depends(ctx.require_auth)]
    settings = ctx.settings
    store = secrets.SecretStore(settings.data_dir)
    credentials = settings.data_dir / "accounts"

    @app.put("/v1/accounts/{name}/login", dependencies=authed)
    async def set_login(name: str, request: Request) -> Response:
        """A token login: the token the person's own sign-in printed, or where they keep it. A
        file login: the credential file its login left."""
        body = parse_body(AccountLoginRequest, await request.body())
        loaded = account_or_404(settings, name)
        if loaded.account is None:
            raise ProblemError(409, "invalid account: fix its file", loaded.error)
        try:
            accounts.save_login(loaded, credentials, store, body)
        except accounts.AccountError as e:
            raise ProblemError(422, "login refused", str(e)) from None
        log.info("account %s: logged in", name)
        return dump(account_info(ctx, name))

    @app.post("/v1/accounts/{name}/login/window", dependencies=authed)
    def open_login_window(name: str) -> Response:
        """A file login: open a terminal window on the desktop running `handler account login
        <name>`, the harness's login, on the host, in the person's own terminal. A token login is
        the person's to run (handler never runs it)."""
        loaded = account_or_404(settings, name)
        if loaded.account is None or loaded.login is None:
            raise ProblemError(409, "invalid account: fix its file", loaded.error)
        if loaded.login.token:
            raise ProblemError(
                409,
                "a token login is yours to run",
                f"run `{loaded.login.token_command}`, then give handler the token it prints",
            )
        argv = [terminal.handler(), "account", "login", name, "--keep-open"]
        env = {"HANDLER_URL": settings.base_url, "HANDLER_CONFIG_DIR": str(settings.config_dir)}
        try:
            opened = terminal.open_window(argv, env)
        except terminal.TerminalError as e:
            raise ProblemError(
                503, "cannot open a terminal", f"{e}; or run: handler account login {name}"
            ) from None
        log.info("account %s: login window opened (%s)", name, opened)
        return dump(
            LoginWindow(terminal=opened, command=f"handler account login {name} --keep-open"),
            status=201,
        )

    @app.delete("/v1/accounts/{name}/login", dependencies=authed)
    def forget_login(name: str) -> Response:
        accounts.forget_login(account_or_404(settings, name), credentials, store)
        log.info("account %s: logged out", name)
        return dump(account_info(ctx, name))


def account_or_404(settings: Settings, name: str) -> accounts.LoadedAccount:
    loaded = accounts.get(settings.accounts_dir, name)
    if not loaded.path.is_file():
        raise ProblemError(404, "account not found", name)
    return loaded


def account_info(ctx: Context, name: str) -> AccountInfo:
    return next(a for a in account_infos(ctx) if a.name == name)


def references(ctx: Context) -> dict[str, dict[str, list[str]]]:
    """The agents using each account and each provider: "<project> · <agent>"; an ad-hoc one by
    its name, else by where it works."""
    found: dict[str, dict[str, list[str]]] = {"account": {}, "provider": {}}
    for record in ctx.registry.agents.values():
        label = ctx.projects.label(record) if record.project_id else ad_hoc_label(record)
        m = record.model
        kind, name = ("account", m.account) if m.account else ("provider", m.provider or "")
        users = found[kind].setdefault(name, [])
        if (label or record.id) not in users:
            users.append(label or record.id)
    return found


def ad_hoc_label(record: AgentRecord) -> str:
    if record.name:
        return record.name
    if record.scope:
        return f"an agent in {PurePath(record.scope).name}"
    return "an agent with a folder per session"


def account_infos(ctx: Context) -> list[AccountInfo]:
    """The accounts, their status, the agents using them and the sessions on them."""
    settings = ctx.settings
    using = references(ctx)["account"]
    store = secrets.SecretStore(settings.data_dir)
    infos = []
    for a in accounts.load_all(settings.accounts_dir):
        names = using.get(a.name, [])
        records = [r for r in ctx.sessions.records.values() if r.account == a.name]
        info: dict[str, Any] = {
            "name": a.name,
            "agents": names,
            "sessions": len(records),
            "last_used_at": max((r.last_activity_at for r in records), default=None),
        }
        if a.account is None or a.login is None:
            infos.append(AccountInfo(**info, status="invalid", error=a.error))
            continue
        credentials = settings.data_dir / "accounts"
        since = accounts.logged_in_at(a, credentials, store)
        expires = accounts.expires_at(a, since)
        problems = []
        if not accounts.logged_in(a, credentials, store):
            problems.append("not logged in")
        elif expires is not None and expires <= datetime.now(UTC):
            problems.append(f"its token expired on {expires.date()}: make a new one")
        token = a.account.token
        infos.append(
            AccountInfo(
                **info,
                harness=a.account.harness,
                description=a.account.description,
                plan=a.account.plan,
                connectors=a.account.connectors,
                areas=a.account.areas,
                login=a.login.kind,
                token=None if token is None else secrets.kind(token),
                logged_in_at=since,
                expires_at=expires,
                hosts=list(a.login.hosts),
                status="incomplete" if problems else "ready",
                problems=problems,
            )
        )
    return infos
