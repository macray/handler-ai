"""Addons in an agent (contract G.3): which bindings it gets, whether they fit together, and what
they add to its launch.

    check      → G3: every binding valid, one per addon, no command twice
    resolve    → G4: image mounts, PATH suffix, env (settings, resolved secrets), egress, skills,
                 MCP servers

`check` runs when an agent is saved (so mistakes surface there) and again at each
agent start (bindings are files: they may have changed since).
"""

from dataclasses import dataclass, field
from pathlib import Path

from handler_contracts import ImageMount, McpServer, StdioMcpServer
from handler_harness import images

from . import bindings, secrets


class SelectionError(ValueError):
    """The selected bindings cannot be used together, or by this agent (G3)."""


@dataclass(frozen=True)
class AddonLaunch:
    """What the selected bindings add to an agent's launch (G4)."""

    image_mounts: list[ImageMount] = field(default_factory=list)
    path_append: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    egress: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)  # skill folders (the agent's too, D.17)
    mcp_servers: list[McpServer] = field(default_factory=list)
    secret_values: list[str] = field(default_factory=list)  # for redaction (invariant 4)
    # env vars holding a secret → its name (bindings/<binding>/<slot>) and the hosts it is for
    # (None: given as it is, the addon says so)
    secret_env: dict[str, tuple[str, list[str] | None]] = field(default_factory=dict)


def check(bindings_dir: Path, selected: list[str]) -> list[bindings.LoadedBinding]:
    """G3. Returns the agent's bindings, all valid, without duplicates; raises
    SelectionError otherwise."""
    names = list(dict.fromkeys(selected))
    loaded = [bindings.get(bindings_dir, name) for name in names]
    for b in loaded:
        if b.error:
            raise SelectionError(f"binding '{b.name}': {b.error}")
    by_addon: dict[str, str] = {}
    by_command: dict[str, str] = {}
    for b in loaded:
        assert b.addon is not None  # valid bindings have their addon
        addon = b.addon.name
        if addon in by_addon:
            raise SelectionError(
                f"bindings '{by_addon[addon]}' and '{b.name}' both use addon '{addon}': "
                "an agent can use one binding per addon"
            )
        by_addon[addon] = b.name
        for command in b.addon.manifest.commands:
            if command in by_command:
                raise SelectionError(
                    f"addons '{by_command[command]}' and '{addon}' both provide '{command}'"
                )
            by_command[command] = addon
    return loaded


def resolve(loaded: list[bindings.LoadedBinding], store: secrets.SecretStore) -> AddonLaunch:
    """G4, for bindings returned by `check`. Resolves secret references (SecretError)."""
    launch = AddonLaunch()
    for b in loaded:
        assert b.binding is not None and b.addon is not None
        manifest = b.addon.manifest
        if manifest.image is not None:
            image = images.ref(manifest.image, images.LATEST)
            launch.image_mounts.append(ImageMount(image=image, target=manifest.mount_target))
            launch.path_append.append(manifest.bin_dir)
        launch.env.update(manifest.env or {})
        for slot, value in (b.binding.settings or {}).items():
            launch.env[manifest.settings[slot].env] = value
        for slot, ref in (b.binding.secrets or {}).items():
            value = secrets.resolve(ref, store)
            env = manifest.secret_slots[slot].env
            launch.env[env] = value
            launch.secret_values.append(value)
            name = secrets.name_of(ref, bindings.secret_path(b.name, slot))
            launch.secret_env[env] = (name, manifest.secret_hosts(slot))
        launch.skills.extend(str(s) for s in b.addon.skills)
    launch.egress.extend(egress(loaded))
    launch.mcp_servers.extend(mcp_servers(loaded))
    return launch


def mcp_servers(loaded: list[bindings.LoadedBinding]) -> list[McpServer]:
    """The MCP servers the addons of bindings returned by `check` provide (G4), each under its
    addon's name, without resolving any secret."""
    found: list[McpServer] = []
    for b in loaded:
        if b.addon and (mcp := b.addon.manifest.mcp):
            command, *args = mcp.command
            found.append(StdioMcpServer(name=b.addon.manifest.name, command=command, args=args))
    return found


def egress(loaded: list[bindings.LoadedBinding]) -> list[str]:
    """The hosts the addons of bindings returned by `check` need (G4), without resolving any
    secret."""
    return sorted({e for b in loaded if b.addon for e in b.addon.manifest.egress})


def secret_values(bindings_dir: Path, selected: list[str], store: secrets.SecretStore) -> list[str]:
    """The secret values of the selected bindings, for redaction; [] if they cannot be read
    (the agent cannot start without them either)."""
    try:
        return resolve(check(bindings_dir, selected), store).secret_values
    except (SelectionError, secrets.SecretError):
        return []
