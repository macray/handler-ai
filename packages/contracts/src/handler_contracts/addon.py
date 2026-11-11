"""Contract G — Tool (`handler.tool/v1`) and connection (`handler.connection/v1`), tools
design. In the code a tool is an `Addon` and a connection a `Binding` (their names before
2026-11-02); every file and word a person reads says tool and connection.

A tool says how to use a kind of system (an image of programs, skills, env, slots, egress); it
is platform-owned data in `tools/<name>/tool.toml`, like a harness descriptor. A connection is
one tool connected to one instance of that system with its settings and secret references; it is
user-owned TOML in `~/.config/handler-ai/connections/<name>.toml`, like an account or a provider.
"""

import tomllib
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .common import (
    Document,
    EgressEntry,
    EnvMap,
    EnvName,
    SecretRef,
    StrictDocument,
)
from .harness import Caches, Command, ImageRepository, NonEmpty
from .sandbox import CA_ENV

ADDON_API_VERSION = "handler.tool/v1"
BINDING_API_VERSION = "handler.connection/v1"

# A tool's image is mounted read-only at <ADDONS_ROOT>/<name>; its `bin/` goes on PATH (G.2).
ADDONS_ROOT = "/opt/tools"
# Every tool image records what it installed here (relative to its root), like IMAGE_VERSION_FILE.
ADDON_VERSION_FILE = "version"

AddonName = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*$")]
BindingName = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
SlotName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
CommandName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$")]

# Env vars the platform owns: a tool may not set them (PATH is extended through `bin/`; the CA
# variables point at the roots the sandbox trusts when its proxy gives secrets, A.3).
RESERVED_ENV = frozenset({"PATH", "HOME", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}) | CA_ENV


class AddonSlot(Document):
    """A setting or secret slot: the connection's value is exported as `env`."""

    env: EnvName
    required: bool = False
    description: str | None = None


class AddonSecretSlot(AddonSlot):
    """A secret slot: its value reaches the agent's sandbox as a phantom its proxy swaps back
    towards `hosts` (E3, A.3), or with `delivery = "env"` as it is, for a tool that cannot be
    given a phantom (it signs its requests with the secret, or speaks something else than HTTP)."""

    hosts: list[EgressEntry] | None = None  # where the secret goes: some of `egress` (default all)
    delivery: Literal["proxy", "env"] = "proxy"


class AddonMcp(Document):
    """An MCP server the tool provides, over stdio, started from one of its own `commands`
    (installed at build time). Added to the agent's MCP servers under the tool's name."""

    command: Annotated[list[NonEmpty], Field(min_length=1)]


class AddonManifest(Document):
    api_version: Literal["handler.tool/v1"]
    name: AddonName
    description: str | None = None
    image: ImageRepository | None = None  # None: a tool without programs (skills, env, egress)
    commands: list[CommandName] = []  # exactly what the image's bin/ provides (checked at build)
    check: Annotated[list[NonEmpty], Field(min_length=1)] | None = None  # run by a rebuild (G.4)
    env: EnvMap | None = None
    settings: dict[SlotName, AddonSlot] = {}
    secret_slots: dict[SlotName, AddonSecretSlot] = {}
    egress: list[EgressEntry] = []
    mcp: AddonMcp | None = None
    needs: list[Command] = []  # what it runs from the toolbox (B.6), checked at its build (G.4)
    caches: Caches = []  # what its tools write, kept between sessions of its agents (D.8)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.image is None and (self.commands or self.check):
            raise ValueError("'commands' and 'check' need an 'image'")
        if self.mcp and self.mcp.command[0] not in self.commands:
            raise ValueError("'mcp.command' must start with one of the tool's 'commands'")
        if self.image is not None and not self.commands:
            raise ValueError("a tool with an 'image' must declare its 'commands'")
        if len(set(self.commands)) != len(self.commands):
            raise ValueError("'commands' has duplicates")
        if own := sorted(set(self.needs) & set(self.commands)):
            raise ValueError(f"'needs' names its own commands: {', '.join(own)}")
        names = [
            *(self.env or {}),
            *(s.env for s in self.settings.values()),
            *(s.env for s in self.secret_slots.values()),
        ]
        if reserved := sorted(set(names) & RESERVED_ENV):
            raise ValueError(f"env vars owned by the platform: {', '.join(reserved)}")
        if len(set(names)) != len(names):
            raise ValueError("an env var is set twice (env, settings and secretSlots must differ)")
        if clash := sorted(self.settings.keys() & self.secret_slots.keys()):
            raise ValueError(f"slot names used for both a setting and a secret: {', '.join(clash)}")
        for name, slot in self.secret_slots.items():
            if slot.hosts is not None and slot.delivery == "env":
                raise ValueError(f"secret {name}: 'hosts' are for the proxy, not 'env' delivery")
            if outside := sorted(set(slot.hosts or []) - set(self.egress)):
                raise ValueError(f"secret {name}: hosts not in 'egress': {', '.join(outside)}")
        return self

    def secret_hosts(self, slot: str) -> list[str] | None:
        """Where a secret slot's value goes through the proxy (A.3); None: given as it is."""
        declared = self.secret_slots[slot]
        if declared.delivery == "env":
            return None
        return list(self.egress if declared.hosts is None else declared.hosts)

    @property
    def has_slots(self) -> bool:
        """An agent uses it through a connection filling them (G.2); else by its name alone."""
        return bool(self.settings or self.secret_slots)

    @property
    def mount_target(self) -> str:
        return f"{ADDONS_ROOT}/{self.name}"

    @property
    def bin_dir(self) -> str:
        return f"{self.mount_target}/bin"


class Binding(StrictDocument):
    api_version: Literal["handler.connection/v1"]
    tool: AddonName
    description: str | None = None
    settings: dict[SlotName, str] | None = None
    secrets: dict[SlotName, SecretRef] | None = None  # references only, never values (E2)

    @classmethod
    def from_toml(cls, text: str) -> "Binding":
        return cls.model_validate(tomllib.loads(text))


def check_binding(binding: Binding, manifest: AddonManifest) -> None:
    """G1: a connection only fills slots its tool declares, and fills every required one; a
    tool without slots has no connection (agents use it by name, G.2). Raises ValueError with a
    readable message."""
    if not manifest.has_slots:
        raise ValueError(f"tool '{manifest.name}' has no settings: it is used without a connection")
    for kind, bound, slots in (
        ("setting", binding.settings or {}, manifest.settings),
        ("secret", binding.secrets or {}, manifest.secret_slots),
    ):
        if unknown := sorted(bound.keys() - slots.keys()):
            raise ValueError(f"{kind} {', '.join(unknown)} not declared by tool '{manifest.name}'")
        if missing := sorted(n for n, s in slots.items() if s.required and n not in bound):
            raise ValueError(f"required {kind} {', '.join(missing)} is missing")
