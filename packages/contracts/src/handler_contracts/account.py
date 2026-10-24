"""Contract E — Account (`handler.account/v1`): a subscription a harness logs in with (Claude Pro, a
ChatGPT plan). One file per account in `~/.config/handler-ai/accounts/<name>.toml`, written
through the Control API (D.9) or by hand. Its login (its harness's `[login]`, contract B): a token
login's `token` is a reference to the token the person gave (handler's secret store, or where they
keep it); a file login's credential file is kept by handler, not in this file."""

import tomllib
from typing import Annotated, Literal

from pydantic import Field

from .common import AccessArea, SecretRef, StrictDocument

ACCOUNT_API_VERSION = "handler.account/v1"


class Account(StrictDocument):
    api_version: Literal["handler.account/v1"]
    harness: Annotated[str, Field(min_length=1)]
    description: str | None = None
    # its subscription's plan, one of its harness's `login.plans` (e.g. "pro"): told to the
    # harness, which cannot learn it from a token login
    plan: Annotated[str, Field(min_length=1)] | None = None
    # its harness may use the account's own connectors (claude.ai MCP servers), where it has
    # some (B.1 accountConnectors): they reach whatever the account connected
    connectors: bool = False
    # a token login's token (E2): `{secret = "accounts/<name>/token"}` when pasted through handler,
    # or where the person keeps it (`env`, `file`, `command`); none until logged in
    token: SecretRef | None = None
    # the areas it may be used in (D.19): their names, or `any`; none: only in
    # projects without an area and outside projects
    areas: list[AccessArea] = []

    @classmethod
    def from_toml(cls, text: str) -> "Account":
        return cls.model_validate(tomllib.loads(text))
