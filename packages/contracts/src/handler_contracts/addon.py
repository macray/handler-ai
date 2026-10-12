"""Contract G — Addon (`handler.addon/v1`) and binding (`handler.binding/v1`),
docs/dev/design/addons.md.

An addon says how to use a kind of system (a tool image, skills, env, slots, egress); it is
platform-owned data in `addons/<name>/addon.toml`, like a harness descriptor. A binding is one
addon bound to one instance of that system with its settings and secret references; it is
user-owned TOML in `~/.config/handler-ai/bindings/<name>.toml`, like an account or a provider.
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
from .harness import ImageRepository, NonEmpty
from .sandbox import CA_ENV

ADDON_API_VERSION = "handler.addon/v1"
BINDING_API_VERSION = "handler.binding/v1"

# An addon's image is mounted read-only at <ADDONS_ROOT>/<name>; its `bin/` goes on PATH (G.2).
ADDONS_ROOT = "/opt/addons"
# Every addon image records what it installed here (relative to its root), like IMAGE_VERSION_FILE.
ADDON_VERSION_FILE = "version"

AddonName = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*$")]
BindingName = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
SlotName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
CommandName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$")]

# Env vars the platform owns: an addon may not set them (PATH is extended through `bin/`; the CA
# variables point at the roots the sandbox trusts when its proxy gives secrets, A.3).
RESERVED_ENV = frozenset({"PATH", "HOME", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}) | CA_ENV


class AddonSlot(Document):
    """A setting or secret slot: the binding's value is exported as `env`."""

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
    """An MCP server the addon provides, over stdio, started from one of its own `commands`
    (installed at build time). Added to the agent's MCP servers under the addon's name."""

    command: Annotated[list[NonEmpty], Field(min_length=1)]


class AddonManifest(Document):
    api_version: Literal["handler.addon/v1"]
    name: AddonName
    description: str | None = None
    image: ImageRepository | None = None  # None: an addon without a tool (skills, env, egress)
    commands: list[CommandName] = []  # exactly what the image's bin/ provides (checked at build)
    check: Annotated[list[NonEmpty], Field(min_length=1)] | None = None  # run by a rebuild (G.4)
    env: EnvMap | None = None
    settings: dict[SlotName, AddonSlot] = {}
    secret_slots: dict[SlotName, AddonSecretSlot] = {}
    egress: list[EgressEntry] = []
    mcp: AddonMcp | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.image is None and (self.commands or self.check):
            raise ValueError("'commands' and 'check' need an 'image'")
        if self.mcp and self.mcp.command[0] not in self.commands:
            raise ValueError("'mcp.command' must start with one of the addon's 'commands'")
        if self.image is not None and not self.commands:
            raise ValueError("an addon with an 'image' must declare its 'commands'")
        if len(set(self.commands)) != len(self.commands):
            raise ValueError("'commands' has duplicates")
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
    def mount_target(self) -> str:
        return f"{ADDONS_ROOT}/{self.name}"

    @property
    def bin_dir(self) -> str:
        return f"{self.mount_target}/bin"


class Binding(StrictDocument):
    api_version: Literal["handler.binding/v1"]
    addon: AddonName
    description: str | None = None
    settings: dict[SlotName, str] | None = None
    secrets: dict[SlotName, SecretRef] | None = None  # references only, never values (E2)

    @classmethod
    def from_toml(cls, text: str) -> "Binding":
        return cls.model_validate(tomllib.loads(text))


def check_binding(binding: Binding, manifest: AddonManifest) -> None:
    """G1: a binding only fills slots its addon declares, and fills every required one.
    Raises ValueError with a readable message."""
    for kind, bound, slots in (
        ("setting", binding.settings or {}, manifest.settings),
        ("secret", binding.secrets or {}, manifest.secret_slots),
    ):
        if unknown := sorted(bound.keys() - slots.keys()):
            raise ValueError(f"{kind} {', '.join(unknown)} not declared by addon '{manifest.name}'")
        if missing := sorted(n for n, s in slots.items() if s.required and n not in bound):
            raise ValueError(f"required {kind} {', '.join(missing)} is missing")
