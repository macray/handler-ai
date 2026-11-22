"""Checking a connection — contract G.2, D.15: its tool's `connectionCheck` run in a short
sandbox as an agent of that connection gets the tool, and nothing more: the toolbox with the
tool's folder on PATH, the tool's env and the connection's settings, its secrets as stand-ins
the sandbox's proxy swaps back towards their hosts, the network filtered and enforced to the
tool's egress alone, an empty folder to work in (no project, no harness). It works when the
command exits 0; what it printed is kept, the secrets' values hidden.

The last check of each connection is kept while handlerd runs (`Checks`), so its page shows it
after a reload; saving or deleting the connection forgets it.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from handler_contracts import AddonUse, BindingCheck

from . import addons, compose, image_check, secrets
from .settings import Settings

OUTPUT_LINES = 20  # what a check printed, its last lines: enough to say why it failed
OUTPUT_CHARS = 4000


@dataclass
class Checks:
    """The last check of each connection, by its name, while handlerd runs."""

    last: dict[str, BindingCheck] = field(default_factory=dict)

    def keep(self, name: str, check: BindingCheck) -> None:
        self.last[name] = check

    def forget(self, *names: str) -> None:
        for name in names:
            self.last.pop(name, None)


async def check(
    settings: Settings, store: secrets.SecretStore, tool: str, binding: str, toolbox: str
) -> BindingCheck:
    """Run `tool`'s connection check with the connection `binding` (valid, of that tool, which
    is ready and has a check) in `toolbox`. A secret that cannot be read, or a sandbox that does
    not start, is a failed check saying why."""
    try:
        selected = addons.check(settings.bindings_dir, [AddonUse(addon=tool, binding=binding)])
        given = addons.resolve(selected, store)
    except (addons.SelectionError, secrets.SecretError) as e:
        return _failed(str(e))
    [chosen] = selected
    argv = chosen.addon.manifest.connection_check
    assert argv is not None  # the route checks it has one
    delivery = secrets.Delivery("filtered")
    env = dict(given.env)
    for var, (name, hosts) in given.secret_env.items():
        env[var] = delivery.give(name, env[var], hosts)
    [folder] = addons.tools(settings, selected)
    hide = secrets.redactor(given.secret_values)
    with image_check.scratch_scope(settings, f"connection-{binding}-") as scope:
        spec = compose.connection_check_spec(
            name=f"handler-check-{uuid.uuid4().hex[:8]}",
            toolbox=toolbox,
            scope=scope,
            argv=list(argv),
            tool=folder,
            env=env,
            egress=given.egress,
            injections=delivery.injections,
        )
        try:
            code, out = await image_check.run_check(spec, lambda _line: None)
        except image_check.ImageCheckError as e:
            return _failed(hide(str(e)))
    output = hide("\n".join(out.splitlines()[-OUTPUT_LINES:]))[-OUTPUT_CHARS:]
    return BindingCheck(
        ok=code == 0,
        at=datetime.now(UTC),
        output=output,
        error=None if code == 0 else f"'{' '.join(argv)}' exited with {code}",
    )


def _failed(error: str) -> BindingCheck:
    return BindingCheck(ok=False, at=datetime.now(UTC), error=error)
