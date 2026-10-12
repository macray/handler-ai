"""Project contexts (D.19): Work, Personal, a client. A project has at most one; an account or a
provider says which contexts it may be used in (`contexts`, E), or `any`. The rule: a project with
a context runs only the accounts and providers made for it or for `any`; a project without one,
and an agent outside projects, run any. A guard against using the wrong account (a work one on a
personal project), not a wall: knowledge, addon configurations and skills are shared.

Stored in <config>/contexts.toml, one table per context with its colour, edited in Settings →
Contexts: `[Work]` `color = "blue"`.
"""

import tomllib
from typing import get_args

import tomlkit

from handler_contracts import ANY_CONTEXT, ContextColor

from . import accounts, providers
from .files import write_private
from .settings import Settings, Sources

CONFIG_FILE = "contexts.toml"
COLORS: tuple[str, ...] = get_args(ContextColor)


class ContextError(ValueError):
    """A model not allowed in a project's context, or a context that cannot be saved."""


def load(settings: Settings) -> dict[str, str]:
    """Name → colour, in the file's order. Read on every call: a change applies at once."""
    try:
        doc = tomllib.loads((settings.config_dir / CONFIG_FILE).read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return {
        name: table["color"]
        for name, table in doc.items()
        if isinstance(table, dict) and table.get("color") in COLORS
    }


def save(settings: Settings, contexts: dict[str, str]) -> None:
    doc = tomlkit.document()
    for name, color in contexts.items():
        table = tomlkit.table()
        table["color"] = color
        doc[name] = table
    write_private(settings.config_dir / CONFIG_FILE, tomlkit.dumps(doc))


def allows(context: str | None, made_for: list[str]) -> bool:
    """Whether an account or provider made for these contexts may run in a project with this
    one (None: no project, or a project without a context)."""
    return context is None or ANY_CONTEXT in made_for or context in made_for


def made_for(sources: Sources, account: str | None, provider: str | None) -> list[str]:
    """The contexts an account or a provider is made for; [] when it cannot be read (its own
    error is reported where it is resolved)."""
    if account is not None:
        loaded = accounts.get(sources.accounts, account)
        return loaded.account.contexts if loaded.account is not None else []
    found = providers.get(sources.providers, provider or "")
    return found.provider.contexts if found.provider is not None else []


def check(sources: Sources, context: str | None, account: str | None, provider: str | None) -> None:
    """ContextError when that account or provider is not made for the project's context."""
    contexts = made_for(sources, account, provider)
    if allows(context, contexts):
        return
    what = f"account {account}" if account is not None else f"provider {provider}"
    made = ", ".join(contexts) if contexts else "no context"
    raise ContextError(f"{what} is not for {context} projects (it is for: {made})")
