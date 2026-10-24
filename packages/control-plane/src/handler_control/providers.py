"""Providers — contract E, D.12: `~/.config/handler-ai/providers/<name>.toml`, an endpoint for
each protocol it speaks, its key and its models, one per file, name = file stem. Written through the
Control API (from a template of `templates/providers/`, or edited), or by hand. Through the API,
its key goes to the secret store (`providers/<name>/apiKey`); a hand-written file may name an
`env`, `file` or `command` key instead, which the API keeps as it is and never writes.

Status: `ready` when its key, if it has one, resolves; `incomplete` with the problem otherwise;
`invalid` when the file is not a valid provider.
"""

from dataclasses import dataclass
from pathlib import Path

import tomlkit
from pydantic import ValidationError

from handler_contracts import (
    PROVIDER_API_VERSION,
    CommandSecret,
    Provider,
    ProviderRequest,
    ProviderTemplate,
    StoreSecret,
)
from handler_harness import catalog

from . import secrets
from .files import describe, write_private


class ProviderError(ValueError):
    pass


@dataclass(frozen=True)
class LoadedProvider:
    name: str
    path: Path
    provider: Provider | None
    error: str | None = None  # set when the file is invalid (its agents are then unusable)


def load(path: Path) -> LoadedProvider:
    name = path.stem
    if not path.is_file():
        return LoadedProvider(name, path, None, f"no provider '{name}' ({path})")
    try:
        provider = Provider.from_toml(path.read_text())
    except ValidationError as e:
        return LoadedProvider(name, path, None, describe(e))
    except (OSError, ValueError) as e:  # unreadable file, TOML syntax error
        return LoadedProvider(name, path, None, str(e))
    return LoadedProvider(name, path, provider)


def get(directory: Path, name: str) -> LoadedProvider:
    if "/" in name or name.startswith("."):
        return LoadedProvider(name, directory / name, None, f"invalid provider name '{name}'")
    return load(directory / f"{name}.toml")


def load_all(directory: Path) -> list[LoadedProvider]:
    if not directory.is_dir():
        return []
    return [load(p) for p in sorted(directory.glob("*.toml"))]


def problems(provider: Provider, store: secrets.SecretStore) -> list[str]:
    """What keeps it from being used as it is: a key that does not resolve. Resolving a `command`
    key runs it: only `env` and `file` ones are checked."""
    ref = provider.api_key
    if ref is None or isinstance(ref, CommandSecret):
        return []
    try:
        secrets.resolve_all({"apiKey": ref}, store)
    except secrets.SecretError as e:
        return [f"apiKey: {e}"]
    return []


def harnesses(provider: Provider) -> list[str]:
    """The harnesses that speak one of its protocols."""
    return [
        h.name
        for h in catalog.all_harnesses()
        if provider.endpoint_for(h.descriptor.provider_protocols) is not None
    ]


def templates(templates_dir: Path) -> list[ProviderTemplate]:
    return [
        ProviderTemplate(
            name=loaded.name,
            description=p.description,
            endpoints=dict(p.endpoints),
            models=p.models,
            needs_key=p.api_key is not None,
            files=p.files,
        )
        for loaded in load_all(templates_dir / "providers")
        if (p := loaded.provider) is not None
    ]


def key_path(name: str) -> str:
    return f"providers/{name}/apiKey"


def save(
    directory: Path,
    store: secrets.SecretStore,
    request: ProviderRequest,
    old: LoadedProvider | None,
) -> LoadedProvider:
    """Create the provider (`old` None) or replace `old`, renaming it to `request.name`: its key
    follows. A new key goes to the secret store; without one, the key it has is kept."""
    name = request.name
    target = directory / f"{name}.toml"
    if (old is None or old.name != name) and target.exists():
        raise ProviderError(f"provider '{name}' exists")
    key = old.provider.api_key if old is not None and old.provider is not None else None
    files = old.provider.files if old is not None and old.provider is not None else None
    if request.files is not None:
        files = request.files
    if old is not None and old.name != name:
        store.rename(f"providers/{old.name}", f"providers/{name}")
        if isinstance(key, StoreSecret) and key.secret == key_path(old.name):
            key = StoreSecret(secret=key_path(name))
    if request.key is not None:
        store.put(key_path(name), request.key, f"key of the provider {name}")
        key = StoreSecret(secret=key_path(name))
    elif request.remove_key:
        store.delete(key_path(name))
        key = None
    provider = Provider(
        api_version=PROVIDER_API_VERSION,
        description=request.description,
        endpoints=request.endpoints,
        api_key=key,
        models=request.models,
        files=files,
        areas=list(dict.fromkeys(request.areas)),
    )
    write_private(target, _toml(provider))
    if old is not None and old.name != name:
        old.path.unlink(missing_ok=True)
    return load(target)


def delete(directory: Path, store: secrets.SecretStore, name: str) -> None:
    (directory / f"{name}.toml").unlink(missing_ok=True)
    store.delete(f"providers/{name}")


def _toml(provider: Provider) -> str:
    data = provider.model_dump(by_alias=True, exclude_defaults=True, mode="json")
    doc = tomlkit.document()
    for field in ("apiVersion", "description", "areas"):
        if field in data:
            doc[field] = data[field]
    if "apiKey" in data:
        key = tomlkit.inline_table()
        key.update(data["apiKey"])
        doc["apiKey"] = key
    doc["endpoints"] = data["endpoints"]
    models = tomlkit.aot()
    for model in data["models"]:
        models.append(tomlkit.item(model))
    doc["models"] = models
    if "files" in data:  # [files.<harness>] slot = { content | file | env = … }
        files = tomlkit.table(is_super_table=True)
        for harness, slots in data["files"].items():
            table = tomlkit.table()
            for slot, source in slots.items():
                entry = tomlkit.inline_table()
                entry.update(source)
                table[slot] = entry
            files[harness] = table
        doc["files"] = files
    return tomlkit.dumps(doc)
