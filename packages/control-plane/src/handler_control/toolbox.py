"""The toolbox as handlerd keeps it (B.6, B.7): what it is made of, what it gives, who needs what.

    toolbox.toml          the user's (handler_harness.catalog): the distro, the system packages on
    <state>/toolbox.json  the record (`ToolboxRecord`): what the toolbox `:latest` gives, every
                          command a need or a system package names → its path; written when a
                          build switches to it (builds.py), read by every check of a need

A need is one of some commands. What is in use needs: Handler itself, every harness (their
images are all built on the toolbox), the addons saved agents use (theirs and their projects',
G.1 `needs`) and the abilities of saved agents (`nested`: an engine).
A need is provided by the base, a system package on, or, when neither names it, the user's lines
(found in the record). A build whose new toolbox lacks a need in use fails (nothing switches); a
system package that alone provides one cannot be turned off.

What a save or an install would need that the toolbox lacks is answered by a system package
providing it (`to_add`): the action says so, and confirming it is the consent (B.6): the system
packages are turned on, then the toolbox applied.
"""

import contextlib
from collections.abc import Iterable
from dataclasses import dataclass

from handler_contracts import (
    ABILITY_NEEDS,
    HANDLER_TOOLBOX_NEEDS,
    Ability,
    AddonUse,
    AgentSettings,
    SystemPackageChoice,
    SystemPackageDaemon,
    SystemPackageInfo,
    ToolboxInfo,
    ToolboxManifest,
    ToolboxNeed,
    ToolboxRecord,
    ToolboxSystemPackage,
)
from handler_harness import addons, catalog, images
from handler_harness import toolbox as parts

from . import runtime
from .agents import AgentRegistry, addons_in_use
from .settings import Settings

RECORD_FILE = "toolbox.json"
CONTEXT_DIR = "toolbox-build"


class ToolboxChangeError(ValueError):
    """System packages that cannot be turned on or off as asked (the message says why)."""


class ToolboxInUseError(ToolboxChangeError):
    """Turning a system package off would take away a need in use."""


# ── the record ──────────────────────────────────────────────────────────


def read_record(settings: Settings) -> ToolboxRecord | None:
    path = settings.state_dir / RECORD_FILE
    with contextlib.suppress(FileNotFoundError):
        return ToolboxRecord.model_validate_json(path.read_text())
    return None


def write_record(settings: Settings, record: ToolboxRecord) -> None:
    path = settings.state_dir / RECORD_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(record.model_dump_json(by_alias=True))
    tmp.replace(path)


def known_commands(manifest: ToolboxManifest) -> list[str]:
    """Every command a need or a system package names: what a build records."""
    found = [*HANDLER_TOOLBOX_NEEDS]
    found += [c for h in catalog.all_harnesses() for c in h.descriptor.needs]
    found += [c for alternatives in ABILITY_NEEDS.values() for c in alternatives]
    for name in addons.names():
        with contextlib.suppress(addons.UnknownAddonError, addons.InvalidAddonError):
            found += addons.get(name).manifest.needs
    with contextlib.suppress(parts.ToolboxError):
        found += parts.distro(manifest.distro).manifest.provides
    for name in parts.names():
        with contextlib.suppress(parts.ToolboxError):
            found += parts.get(name).manifest.provides
    return sorted(set(found))


def daemons(settings: Settings) -> list[SystemPackageDaemon]:
    """The daemons of the system packages the toolbox `:latest` was built with (the record),
    as their manifests declare them (B.7); none before a first build."""
    record = read_record(settings)
    found: list[SystemPackageDaemon] = []
    for name in record.system_packages if record else []:
        with contextlib.suppress(parts.ToolboxError, parts.UnknownSystemPackageError):
            found += parts.get(name).manifest.daemons
    return found


# ── needs ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Need:
    commands: tuple[str, ...]  # one of them
    by: str  # "handler", "harness:<name>", "addon:<name>", "agent:<id>"


def abilities_of(settings: AgentSettings) -> list[Ability]:
    """The abilities an agent's sandboxes have (A.8) that need something of the toolbox."""
    if settings.model_alone:
        return []
    found: list[Ability] = []
    if settings.confinement != "strict":
        found.append(settings.confinement)
    if settings.display:
        found.append("display")
    return found


def agent_abilities(registry: AgentRegistry) -> Iterable[tuple[str, Ability]]:
    """The abilities saved agents' sandboxes have (A.8) that need something of the toolbox."""
    for agent in list(registry.agents.values()):
        for ability in abilities_of(agent):
            yield agent.id, ability


def addon_needs(name: str) -> list[Need]:
    with contextlib.suppress(addons.UnknownAddonError, addons.InvalidAddonError):
        return [Need((c,), f"addon:{name}") for c in addons.get(name).manifest.needs]
    return []  # its checks say why


def agent_needs(settings: AgentSettings, given: Iterable[AddonUse], by: str) -> list[Need]:
    """What an agent's sandboxes need of the toolbox: its addons' (its own and its project's,
    `given`) and its abilities'. Its harness's are in use already: every harness is built."""
    if settings.model_alone:
        return []  # no sandbox
    found = [n for use in [*settings.addons, *given] for n in addon_needs(use.addon)]
    return found + [Need(tuple(ABILITY_NEEDS[a]), by) for a in abilities_of(settings)]


def needs_in_use(registry: AgentRegistry) -> list[Need]:
    found = [Need((c,), "handler") for c in HANDLER_TOOLBOX_NEEDS]
    for harness in catalog.all_harnesses():
        found += [Need((c,), f"harness:{harness.name}") for c in harness.descriptor.needs]
    for name in sorted(addons_in_use(list(registry.agents.values()))):
        found += addon_needs(name)
    for agent_id, ability in agent_abilities(registry):
        found.append(Need(tuple(ABILITY_NEEDS[ability]), f"agent:{agent_id}"))
    return found


def grouped(needs: Iterable[Need]) -> dict[tuple[str, ...], list[str]]:
    """Each need's commands → who needs them, in order."""
    by: dict[tuple[str, ...], list[str]] = {}
    for need in needs:
        if need.by not in (who := by.setdefault(need.commands, [])):
            who.append(need.by)
    return by


def declared_providers(manifest: ToolboxManifest, packages: Iterable[str]) -> dict[str, str]:
    """Command → what declares it, of the base and the system packages `packages` (the first
    one wins)."""
    found: dict[str, str] = {}
    with contextlib.suppress(parts.ToolboxError):
        found |= dict.fromkeys(parts.distro(manifest.distro).manifest.provides, "base")
    for name in packages:
        with contextlib.suppress(parts.ToolboxError, parts.UnknownSystemPackageError):
            for command in parts.get(name).manifest.provides:
                found.setdefault(command, f"system-package:{name}")
    return found


def provider(
    commands: tuple[str, ...], declared: dict[str, str], record: ToolboxRecord | None
) -> str | None:
    """What gives one of `commands`: the base or a system package declaring it; else the user's
    lines, when the toolbox built now has it. None: nothing."""
    for command in commands:
        if command in declared:
            return declared[command]
    if record is not None and any(c in record.commands for c in commands):
        return "lines"
    return None


def missing(needs: Iterable[Need], commands: dict[str, str]) -> list[str]:
    """What a toolbox giving `commands` lacks, each with who needs it."""
    return [
        f"{' or '.join(c)} (needed by {', '.join(who)})"
        for c, who in grouped(needs).items()
        if not any(command in commands for command in c)
    ]


def providing(command: str, distro: str) -> parts.SystemPackage | None:
    """A system package Handler or the user has that provides `command` on `distro`."""
    for name in parts.names():
        with contextlib.suppress(parts.ToolboxError, parts.UnknownSystemPackageError):
            package = parts.get(name)
            if command in package.manifest.provides and distro in package.distros:
                return package
    return None


@dataclass(frozen=True)
class Lacking:
    """What `needs` lack of the toolbox: the system packages to turn on for them (each with the
    commands it answers), and the needs no system package provides."""

    adds: dict[str, list[str]]
    unprovided: list[str]


def to_add(settings: Settings, needs: Iterable[Need]) -> Lacking:
    """What the toolbox lacks for `needs` (neither the base, a system package on, nor the toolbox
    built now gives them), and the system packages that would answer it; of a need with
    alternatives (an ability's engines), the first one provided."""
    try:
        manifest = catalog.toolbox()
    except (OSError, ValueError):
        return Lacking({}, [])  # its own problem, shown with the toolbox (`info`)
    declared = declared_providers(manifest, manifest.system_packages)
    record = read_record(settings)
    adds: dict[str, list[str]] = {}
    unprovided = []
    for commands in grouped(needs):
        if provider(commands, declared, record):
            continue
        found = next(
            ((p, c) for c in commands if (p := providing(c, manifest.distro))), (None, None)
        )
        package, command = found
        if package is None or command is None:
            unprovided.append(" or ".join(commands))
        elif command not in (answered := adds.setdefault(package.name, [])):
            answered.append(command)
    return Lacking(adds, unprovided)


def turn_on(registry: AgentRegistry, names: Iterable[str]) -> ToolboxManifest:
    """System packages turned on after those on (ToolboxChangeError, as `set_system_packages`)."""
    return set_system_packages(registry, [*catalog.toolbox().system_packages, *names])


# ── what handlerd shows and changes ─────────────────────────────────────


def info(settings: Settings, registry: AgentRegistry) -> ToolboxInfo:
    latest = runtime.inspect(images.ref(images.TOOLBOX, images.LATEST))
    record = read_record(settings)
    image = ToolboxInfo(
        image=images.TOOLBOX,
        image_present=latest is not None,
        built_at=latest.created if latest else None,
        directory=str(catalog.toolbox_dir()),
        commands=record.commands if record else {},
    )
    try:
        manifest = catalog.toolbox()
    except (OSError, ValueError) as e:
        return image.model_copy(update={"problem": f"toolbox.toml: {e}"})
    problem = None
    try:
        parts.ordered(manifest)
    except parts.ToolboxError as e:
        problem = str(e)
    declared = declared_providers(manifest, manifest.system_packages)
    needs = [
        ToolboxNeed(commands=list(c), needed_by=who, provided_by=provider(c, declared, record))
        for c, who in grouped(needs_in_use(registry)).items()
    ]
    built = record.system_packages if record else {}
    on = []
    for name in manifest.system_packages:
        version = None
        with contextlib.suppress(parts.ToolboxError, parts.UnknownSystemPackageError):
            version = parts.get(name).manifest.version
        needed_by = [
            who for n in needs if n.provided_by == f"system-package:{name}" for who in n.needed_by
        ]
        on.append(
            ToolboxSystemPackage(
                name=name, version=version, built_version=built.get(name), needed_by=needed_by
            )
        )
    return image.model_copy(
        update={
            "distro": manifest.distro,
            "system_packages": on,
            "needs": needs,
            "problem": problem,
        }
    )


def system_packages() -> list[SystemPackageInfo]:
    """Every system package, built-in or the user's; an invalid one with its error."""
    found = []
    for name in parts.names():
        try:
            package = parts.get(name)
        except parts.InvalidSystemPackageError as e:
            directory = parts.user_dir() / name
            if not (directory / "package.toml").is_file():
                directory = parts.BUILTIN_DIR / name
            found.append(
                SystemPackageInfo(
                    name=name,
                    builtin=directory.parent == parts.BUILTIN_DIR,
                    directory=str(directory),
                    error=str(e),
                )
            )
            continue
        m = package.manifest
        found.append(
            SystemPackageInfo(
                name=name,
                version=m.version,
                description=m.description,
                provides=m.provides,
                caches=m.caches,
                daemons=m.daemons,
                distros=package.distros,
                builtin=package.builtin,
                overrides_builtin=package.overrides_builtin,
                directory=str(package.directory),
            )
        )
    return found


def set_system_packages(registry: AgentRegistry, names: list[str]) -> ToolboxManifest:
    """Turn system packages on (with what they depend on) or off, in `names`' order; those
    already on keep their place (and their layers). Raises ToolboxChangeError: unknown, invalid,
    not for the distro; ToolboxInUseError: one turned off alone gave a need in use. Starts
    nothing: the next toolbox build applies it."""
    manifest = catalog.toolbox()
    try:
        chosen = parts.with_dependencies(names)
        for name in chosen:
            if manifest.distro not in parts.get(name).distros:
                raise ToolboxChangeError(
                    f"system package '{name}' has no install script for {manifest.distro}"
                )
    except (parts.ToolboxError, parts.UnknownSystemPackageError) as e:
        raise ToolboxChangeError(str(e)) from None
    order = [n for n in manifest.system_packages if n in chosen]
    order += [n for n in chosen if n not in order]
    before = declared_providers(manifest, manifest.system_packages)
    after = declared_providers(manifest, order)
    lost = [
        f"{' or '.join(c)} ({', '.join(who)})"
        for c, who in grouped(needs_in_use(registry)).items()
        if provider(c, before, None) and not provider(c, after, None)
    ]
    if lost:
        raise ToolboxInUseError(f"still needed: {'; '.join(lost)}")
    on = {name: SystemPackageChoice() for name in order}
    updated = manifest.model_copy(update={"system_packages": on})
    catalog.save_toolbox(updated)
    return updated
