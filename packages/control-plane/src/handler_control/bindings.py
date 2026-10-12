"""Bindings — contract G.2: `~/.config/handler-ai/bindings/<name>.toml`, one per file, name =
file stem. Written through the Control API (D.15: its secret values go to the secret store,
`bindings/<name>/<slot>`), or by hand (a hand-written `env`, `file` or `command` reference is kept
by the API, never written by it).

A binding is valid when its file parses (unknown keys are errors), its addon exists and is valid,
and it fills exactly the slots that addon declares (G2).
"""

from dataclasses import dataclass
from pathlib import Path

import tomlkit
from pydantic import ValidationError

from handler_contracts import (
    BINDING_API_VERSION,
    Binding,
    BindingRequest,
    SecretRef,
    StoreSecret,
    check_binding,
)
from handler_harness import addons

from . import secrets
from .files import describe, write_private


class BindingError(ValueError):
    pass


@dataclass(frozen=True)
class LoadedBinding:
    name: str
    path: Path
    binding: Binding | None  # set even when the addon check fails, for display
    addon: addons.Addon | None
    error: str | None = None  # set when the binding is invalid (it cannot be selected)


def load(path: Path) -> LoadedBinding:
    name = path.stem
    try:
        binding = Binding.from_toml(path.read_text())
    except ValidationError as e:
        return LoadedBinding(name, path, None, None, describe(e))
    except (OSError, ValueError) as e:  # unreadable file, TOML syntax error
        return LoadedBinding(name, path, None, None, str(e))
    try:
        addon = addons.get(binding.addon)
        check_binding(binding, addon.manifest)
    except (addons.UnknownAddonError, ValueError) as e:  # InvalidAddonError is a ValueError
        return LoadedBinding(name, path, binding, None, str(e))
    return LoadedBinding(name, path, binding, addon)


def get(directory: Path, name: str) -> LoadedBinding:
    """A binding by name; unknown → LoadedBinding with an error (the caller decides)."""
    path = directory / f"{name}.toml"
    if "/" in name or name.startswith(".") or not path.is_file():
        return LoadedBinding(name, path, None, None, f"unknown binding '{name}' (no {path})")
    return load(path)


def load_all(directory: Path) -> list[LoadedBinding]:
    if not directory.is_dir():
        return []
    return [load(p) for p in sorted(directory.glob("*.toml"))]


def secret_path(name: str, slot: str) -> str:
    return f"bindings/{name}/{slot}"


def save(
    directory: Path,
    store: secrets.SecretStore,
    request: BindingRequest,
    old: LoadedBinding | None,
) -> LoadedBinding:
    """Create the binding (`old` None) or replace `old`, renaming it to `request.name`: its secrets
    follow. New secret values go to the secret store; a slot without one keeps its reference,
    unless it is in `request.remove_secrets`. Raises BindingError (exists, or not what its addon
    declares: G2)."""
    name = request.name
    target = directory / f"{name}.toml"
    if (old is None or old.name != name) and target.exists():
        raise BindingError(f"binding '{name}' exists")
    try:
        addon = addons.get(request.addon)
    except (addons.UnknownAddonError, ValueError) as e:
        raise BindingError(str(e)) from None
    if old is not None and old.binding is not None and old.binding.addon != request.addon:
        raise BindingError(f"a binding's addon cannot change (it is '{old.binding.addon}')")
    kept: dict[str, SecretRef] = dict(old.binding.secrets or {}) if old and old.binding else {}
    renamed = old if old is not None and old.name != name else None
    if renamed is not None:
        for slot, ref in kept.items():
            if isinstance(ref, StoreSecret) and ref.secret == secret_path(renamed.name, slot):
                kept[slot] = StoreSecret(secret=secret_path(name, slot))
    for slot in request.remove_secrets:
        kept.pop(slot, None)
    binding = Binding(
        api_version=BINDING_API_VERSION,
        addon=request.addon,
        description=request.description,
        settings=request.settings or None,
        secrets={**kept, **{s: StoreSecret(secret=secret_path(name, s)) for s in request.secrets}}
        or None,
    )
    try:
        check_binding(binding, addon.manifest)
    except ValueError as e:
        raise BindingError(str(e)) from None
    if renamed is not None:
        store.rename(f"bindings/{renamed.name}", f"bindings/{name}")
    for slot in request.remove_secrets:
        store.delete(secret_path(name, slot))
    for slot, value in request.secrets.items():
        store.put(secret_path(name, slot), value, f"{slot} of the binding {name} ({request.addon})")
    write_private(target, _toml(binding))
    if renamed is not None:
        renamed.path.unlink(missing_ok=True)
    return load(target)


def delete(directory: Path, store: secrets.SecretStore, name: str) -> None:
    (directory / f"{name}.toml").unlink(missing_ok=True)
    store.delete(f"bindings/{name}")


def _toml(binding: Binding) -> str:
    data = binding.model_dump(by_alias=True, exclude_none=True, mode="json")
    doc = tomlkit.document()
    for field in ("apiVersion", "addon", "description"):
        if field in data:
            doc[field] = data[field]
    if "settings" in data:
        doc["settings"] = data["settings"]
    if "secrets" in data:
        table = tomlkit.table()
        for slot, ref in data["secrets"].items():
            inline = tomlkit.inline_table()
            inline.update(ref)
            table[slot] = inline
        doc["secrets"] = table
    return tomlkit.dumps(doc)
