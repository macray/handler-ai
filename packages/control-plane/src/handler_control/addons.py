"""Addons in an agent (contract G.3): which addons it uses (its own and its project's), whether
they fit together, and what they add to its launch.

    check      → G3: every addon valid, one use per addon, a binding exactly when the addon has
                 slots (the binding valid, of that addon), no command twice, its caches' folders
                 their own
    resolve    → G4: env (settings, resolved secrets), egress, skills, MCP servers
    tools      → G4: the addons' tools (their folders, addon_folders; their commands' folders)

`check` runs when an agent or its project is saved (so mistakes surface there) and again at each
agent start (addons and bindings are files: they may have changed since).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from handler_contracts import Addon, AddonUse, McpServer, StdioMcpServer, cache_name
from handler_harness import addons as catalog

from . import addon_folders, bindings, caches, secrets
from .settings import Settings


class SelectionError(ValueError):
    """The selected addons cannot be used together, or by this agent (G3)."""


@dataclass(frozen=True)
class Selected:
    """An addon an agent uses, checked: with its binding when it has slots."""

    addon: catalog.Addon
    binding: bindings.LoadedBinding | None = None


@dataclass(frozen=True)
class AddonLaunch:
    """What the selected addons add to an agent's launch (G4)."""

    images: list[Addon] = field(default_factory=list)  # the addons' tools (A.1 `addons`): `tools`
    env: dict[str, str] = field(default_factory=dict)
    egress: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)  # skill folders (the agent's too, D.17)
    mcp_servers: list[McpServer] = field(default_factory=list)
    secret_values: list[str] = field(default_factory=list)  # for redaction (invariant 4)
    # env vars holding a secret → its name (bindings/<binding>/<slot>) and the hosts it is for
    # (None: given as it is, the addon says so)
    secret_env: dict[str, tuple[str, list[str] | None]] = field(default_factory=dict)


def _selected(bindings_dir: Path, use: AddonUse) -> Selected:
    try:
        addon = catalog.get(use.addon)
    except (catalog.UnknownAddonError, catalog.InvalidAddonError) as e:
        raise SelectionError(str(e)) from None
    if not addon.manifest.has_slots:
        if use.binding is not None:
            raise SelectionError(
                f"tool '{use.addon}' has no settings: it is used without a connection"
            )
        return Selected(addon)
    if use.binding is None:
        raise SelectionError(f"tool '{use.addon}' needs a connection (its settings and secrets)")
    loaded = bindings.get(bindings_dir, use.binding)
    if loaded.error:
        raise SelectionError(f"connection '{use.binding}': {loaded.error}")
    assert loaded.binding is not None  # a valid binding
    if loaded.binding.tool != use.addon:
        raise SelectionError(
            f"connection '{use.binding}' is one of tool '{loaded.binding.tool}', not '{use.addon}'"
        )
    return Selected(addon, loaded)


def check(bindings_dir: Path, uses: Iterable[AddonUse]) -> list[Selected]:
    """G3, for an agent's own addons and its project's together. Returns them checked; raises
    SelectionError otherwise."""
    found: list[Selected] = []
    by_command: dict[str, str] = {}
    for use in uses:
        if any(s.addon.name == use.addon for s in found):
            raise SelectionError(
                f"tool '{use.addon}' is chosen twice (by the agent and by its project?)"
            )
        selected = _selected(bindings_dir, use)
        for command in selected.addon.manifest.commands:
            if command in by_command:
                raise SelectionError(
                    f"tools '{by_command[command]}' and '{use.addon}' both provide '{command}'"
                )
            by_command[command] = use.addon
        found.append(selected)
    if any(s.addon.manifest.caches for s in found):
        declared = caches.declared()
        for s in found:
            for cache in s.addon.manifest.caches:
                info = declared.get(cache_name(cache.target))
                if info is not None and info.target != cache.target:
                    raise SelectionError(
                        f"tool '{s.addon.name}': its cache {cache.target} would share the "
                        f"folder of {info.target}"
                    )
    return found


def resolve(selected: list[Selected], store: secrets.SecretStore) -> AddonLaunch:
    """G4, for addons returned by `check`. Resolves secret references (SecretError)."""
    launch = AddonLaunch()
    for s in selected:
        manifest = s.addon.manifest
        launch.env.update(manifest.env or {})
        if s.binding is not None:
            assert s.binding.binding is not None  # checked
            for slot, value in (s.binding.binding.settings or {}).items():
                launch.env[manifest.settings[slot].env] = value
            for slot, ref in (s.binding.binding.secrets or {}).items():
                value = secrets.resolve(ref, store)
                env = manifest.secret_slots[slot].env
                launch.env[env] = value
                launch.secret_values.append(value)
                name = secrets.name_of(ref, bindings.secret_path(s.binding.name, slot))
                launch.secret_env[env] = (name, manifest.secret_hosts(slot))
        launch.skills.extend(str(skill) for skill in s.addon.skills)
    launch.egress.extend(egress(selected))
    launch.mcp_servers.extend(mcp_servers(selected))
    return launch


def tools(settings: Settings, selected: list[Selected]) -> list[Addon]:
    """The folders of the addons with a tool, each read-only at <ADDONS_ROOT>/<name>, its bin/ on
    PATH; one not built yet names a folder that does not exist (a launch refuses it, A.7)."""
    return [
        Addon(
            source=str(addon_folders.folder(settings, s.addon.name)),
            target=s.addon.manifest.mount_target,
            path=s.addon.manifest.bin_dir,
        )
        for s in selected
        if s.addon.manifest.image is not None
    ]


def mcp_servers(selected: list[Selected]) -> list[McpServer]:
    """The MCP servers the addons returned by `check` provide (G4), each under its addon's name,
    without resolving any secret."""
    found: list[McpServer] = []
    for s in selected:
        if mcp := s.addon.manifest.mcp:
            command, *args = mcp.command
            found.append(StdioMcpServer(name=s.addon.name, command=command, args=args))
    return found


def egress(selected: list[Selected]) -> list[str]:
    """The hosts the addons returned by `check` need (G4), without resolving any secret."""
    return sorted({e for s in selected for e in s.addon.manifest.egress})


def secret_values(
    bindings_dir: Path, uses: Iterable[AddonUse], store: secrets.SecretStore
) -> list[str]:
    """The secret values of the selected addons' bindings, for redaction; [] if they cannot be
    read (the agent cannot start without them either)."""
    try:
        return resolve(check(bindings_dir, uses), store).secret_values
    except (SelectionError, secrets.SecretError):
        return []
