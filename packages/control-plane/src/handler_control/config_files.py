"""Resolving config file sources (a provider's `files` for a harness) into contents, before
`render`.

{ file = "/abs/path" }    read from the host (e.g. your own ~/.vibe/config.toml)
{ env = "NAME" }          the value of an environment variable of the daemon
{ content = "…" }         inline in the provider file
"""

import os
from pathlib import Path

from handler_contracts import EnvSecret, FileContent, FileSecret, FileSource

MAX_BYTES = 1024 * 1024


class ConfigFileError(RuntimeError):
    pass


def resolve(source: FileSource) -> str:
    if isinstance(source, FileContent):
        return source.content
    if isinstance(source, EnvSecret):
        value = os.environ.get(source.env)
        if value is None:
            raise ConfigFileError(f"environment variable {source.env} is not set")
        return value
    if isinstance(source, FileSecret):
        path = Path(source.file)
        try:
            if path.stat().st_size > MAX_BYTES:
                raise ConfigFileError(f"{path} is larger than {MAX_BYTES} bytes")
            return path.read_text()
        except OSError as e:
            raise ConfigFileError(f"cannot read {path}: {e.strerror}") from None
    raise ConfigFileError(f"unsupported file source {source!r}")


def resolve_all(sources: dict[str, FileSource] | None) -> dict[str, str]:
    return {slot: resolve(source) for slot, source in (sources or {}).items()}
