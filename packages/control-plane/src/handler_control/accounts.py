"""Accounts — contract E, D.9: `~/.config/handler-ai/accounts/<name>.toml`, a subscription one
harness logs in with (its harness, a description, its plan), one per file, name = file stem. Written
through the Control API, or by hand.

Its login (the harness's `[login]`, contract B): a token login's token is the person's own (they
run the harness's sign-in themselves, handler never runs it nor reads its output): pasted, it is
kept in the secret store (`accounts/<name>/token`), else where they keep it; the file says which
(`token`, a reference). A file login's credential file, left by the login handler runs, is kept in
`<data>/accounts/<name>/credential`.

Status: `ready` when logged in; `incomplete` when not yet; `invalid` when the file is not a valid
account, or names a harness that is unknown or has no login (it runs on providers only).
"""

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import tomlkit
from pydantic import ValidationError

from handler_contracts import (
    ACCOUNT_API_VERSION,
    Account,
    AccountLoginRequest,
    LoginRecipe,
    SecretRef,
    StoreSecret,
)
from handler_harness import catalog

from . import secrets
from .files import describe, write_private


@dataclass(frozen=True)
class LoadedAccount:
    name: str
    path: Path
    account: Account | None
    error: str | None = None  # set when the file is invalid (its agents are then unusable)
    login: LoginRecipe | None = None  # its harness's


class AccountError(ValueError):
    pass


def load(path: Path) -> LoadedAccount:
    name = path.stem
    if not path.is_file():
        return LoadedAccount(name, path, None, f"no account '{name}' ({path})")
    try:
        account = Account.from_toml(path.read_text())
    except ValidationError as e:
        return LoadedAccount(name, path, None, describe(e))
    except (OSError, ValueError) as e:  # unreadable file, TOML syntax error
        return LoadedAccount(name, path, None, str(e))
    try:
        descriptor = catalog.get(account.harness).descriptor
    except catalog.UnknownHarnessError as e:
        return LoadedAccount(name, path, None, str(e))
    login = descriptor.login
    product = descriptor.product
    if login is None:
        error = f"{product} has no sign-in of its own: it runs on a provider"
    elif account.token is not None and login.token is None:
        error = f"token: {product} signs in with a file, not a token"
    elif account.connectors and descriptor.account_connectors is None:
        error = f"connectors: {product} has no account connectors"
    else:
        error = plan_error(account.harness, login, account.plan)
    if error is not None:
        return LoadedAccount(name, path, None, error)
    return LoadedAccount(name, path, account, login=login)


def plan_error(harness: str, login: LoginRecipe, plan: str | None) -> str | None:
    """A plan must be one its harness's login knows."""
    if plan is None or plan in login.plans:
        return None
    if not login.plans:
        return f"plan: harness '{harness}' has no plans"
    return f"plan: '{plan}' is not one of {', '.join(login.plans)}"


def get(directory: Path, name: str) -> LoadedAccount:
    if "/" in name or name.startswith("."):
        return LoadedAccount(name, directory / name, None, f"invalid account name '{name}'")
    return load(directory / f"{name}.toml")


def load_all(directory: Path) -> list[LoadedAccount]:
    if not directory.is_dir():
        return []
    return [load(p) for p in sorted(directory.glob("*.toml"))]


def token_path(name: str) -> str:
    return f"accounts/{name}/token"


def credential_file(credentials: Path, name: str) -> Path:
    """A file login's file, alone in its folder (contract A.1: a writable file mount)."""
    return credentials / name / "login" / "credential"


def logged_in(loaded: LoadedAccount, credentials: Path, store: secrets.SecretStore) -> bool:
    return logged_in_at(loaded, credentials, store) is not None or (
        loaded.account is not None
        and loaded.account.token is not None
        and not isinstance(loaded.account.token, StoreSecret)  # a reference: handler cannot tell
    )


def logged_in_at(
    loaded: LoadedAccount, credentials: Path, store: secrets.SecretStore
) -> datetime | None:
    """When handler was given its login: its token's in the secret store, or the file a file login
    left. None when not logged in, or when its token is a reference (env, file, command)."""
    if loaded.login is None or loaded.account is None:
        return None
    if loaded.login.token:
        ref = loaded.account.token
        if not isinstance(ref, StoreSecret):
            return None
        info = next((i for i in store.list() if i.path == ref.secret), None)
        return info.updated_at if info else None
    file = credential_file(credentials, loaded.name)
    return datetime.fromtimestamp(file.stat().st_mtime, UTC) if file.is_file() else None


def expires_at(loaded: LoadedAccount, since: datetime | None) -> datetime | None:
    """When a token given at `since` stops working, if its harness says how long one lasts."""
    days = loaded.login.token_lifetime_days if loaded.login else None
    return since + timedelta(days=days) if since and days else None


def create(
    directory: Path,
    name: str,
    harness: str,
    description: str | None,
    *,
    plan: str | None = None,
    connectors: bool = False,
    areas: list[str] | None = None,
) -> LoadedAccount:
    target = directory / f"{name}.toml"
    if target.exists():
        raise AccountError(f"account '{name}' exists")
    _write(target, harness, description, plan, connectors, areas or [])
    loaded = load(target)
    if loaded.account is None:
        target.unlink()
        raise AccountError(loaded.error or "invalid account")
    return loaded


def update(
    directory: Path,
    credentials: Path,
    store: secrets.SecretStore,
    old: LoadedAccount,
    *,
    name: str,
    description: str | None,
    plan: str | None = None,
    connectors: bool = False,
    areas: list[str] | None = None,
) -> LoadedAccount:
    """Its description, its plan, its connectors, its areas, and its name: the file, the login
    and its token follow."""
    assert old.account is not None and old.login is not None
    if (error := plan_error(old.account.harness, old.login, plan)) is not None:
        raise AccountError(error)
    target = directory / f"{name}.toml"
    token = old.account.token
    if name != old.name:
        if target.exists():
            raise AccountError(f"account '{name}' exists")
        if (kept := credentials / old.name).exists():
            kept.rename(credentials / name)
        store.rename(f"accounts/{old.name}", f"accounts/{name}")
        if isinstance(token, StoreSecret) and token.secret == token_path(old.name):
            token = StoreSecret(secret=token_path(name))
        old.path.unlink()
    _write(target, old.account.harness, description, plan, connectors, areas or [], token)
    loaded = load(target)
    if loaded.account is None:
        raise AccountError(loaded.error or "invalid account")
    return loaded


def delete(directory: Path, credentials: Path, store: secrets.SecretStore, name: str) -> None:
    (directory / f"{name}.toml").unlink(missing_ok=True)
    shutil.rmtree(credentials / name, ignore_errors=True)
    store.delete(f"accounts/{name}")


def token_error(login: LoginRecipe, token: str) -> str | None:
    """Why a token login's token is not one its harness takes (its `tokenPrefix`), or None."""
    if login.token_prefix is None or token.startswith(login.token_prefix):
        return None
    return (
        f"not the token `{login.token_command}` prints (it starts with {login.token_prefix}): "
        "a code its sign-in page shows goes back into it, not to handler"
    )


def save_login(
    loaded: LoadedAccount,
    credentials: Path,
    store: secrets.SecretStore,
    request: AccountLoginRequest,
) -> None:
    """Keep its login: a token login's token (pasted: into the secret store; or a reference to
    where the person keeps it), or the content of a file login's credential file."""
    login, account = loaded.login, loaded.account
    assert login is not None and account is not None
    if login.token:
        if request.file is not None:
            raise AccountError(f"the login of '{loaded.name}' is a token")
        ref: SecretRef
        if request.token is not None:
            if (error := token_error(login, request.token)) is not None:
                raise AccountError(error)
            description = f"login of the account {loaded.name}"
            store.put(token_path(loaded.name), request.token, description)
            ref = StoreSecret(secret=token_path(loaded.name))
        else:
            assert request.token_ref is not None
            store.delete(token_path(loaded.name))  # a pasted one it had
            ref = request.token_ref
        _rewrite(loaded, ref)
        return
    if request.file is None:
        raise AccountError(f"the login of '{loaded.name}' is a file")
    write_private(credential_file(credentials, loaded.name), request.file)


def forget_login(loaded: LoadedAccount, credentials: Path, store: secrets.SecretStore) -> None:
    shutil.rmtree(credentials / loaded.name, ignore_errors=True)
    store.delete(token_path(loaded.name))
    if loaded.account is not None and loaded.account.token is not None:
        _rewrite(loaded, None)


def _rewrite(loaded: LoadedAccount, token: SecretRef | None) -> None:
    a = loaded.account
    assert a is not None
    _write(loaded.path, a.harness, a.description, a.plan, a.connectors, a.areas, token)


def _write(  # noqa: PLR0917 — the account file's fields, in its order
    target: Path,
    harness: str,
    description: str | None,
    plan: str | None,
    connectors: bool,
    areas: list[str],
    token: SecretRef | None = None,
) -> None:
    doc = tomlkit.document()
    doc["apiVersion"] = ACCOUNT_API_VERSION
    doc["harness"] = harness
    if description:
        doc["description"] = description
    if plan:
        doc["plan"] = plan
    if connectors:
        doc["connectors"] = True
    if areas:
        doc["areas"] = list(dict.fromkeys(areas))
    if token is not None:
        ref = tomlkit.inline_table()
        ref.update(token.model_dump(by_alias=True, exclude_none=True))
        doc["token"] = ref
    write_private(target, tomlkit.dumps(doc))
