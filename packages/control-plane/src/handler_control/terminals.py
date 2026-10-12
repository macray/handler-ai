"""D.16 — a harness's own terminal program (`handler terminal`): its sandbox, started for a client.

The sandbox holds the program's terminal (A.1 `tty`): handlerd starts it, then the client attaches
its own terminal to it (`TerminalStarted.attach`), without handlerd in between. The launcher runs
out of handlerd's reach (`sandbox_process.start_detached`), so restarting handlerd leaves the
program running. Until then the sandbox is one of the agent's connections: live egress switching
(A.4) and egress events apply. Nothing crosses ACP, so the policy pipeline (C.4) has nothing to see;
the sandbox (A) is what contains the program.
"""

import asyncio
import contextlib
import logging
import os
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from handler_contracts import TerminalStart, TerminalStarted

from . import launcher, sandbox_process
from .agents import AgentRecord, AgentRegistry, LiveConnection, RunsAs
from .settings import Settings

log = logging.getLogger("handler.terminal")

READY_LINE = "handler-ready"  # the sandbox's, on its stderr: it waits for the client's `attach` (A)
READY_TIMEOUT = 600.0  # seconds: a first start may build the egress proxy's image

_followed: set[asyncio.Task[None]] = set()  # until each launcher ends


class TerminalStartError(Exception):
    """The sandbox did not start: the reason, from its launcher."""


async def start(
    settings: Settings,
    record: AgentRecord,
    registry: AgentRegistry,
    start: TerminalStart,
    runs: RunsAs,
) -> TerminalStarted:
    """Start the sandbox, running as `runs` (checks.session_model), and wait until it is ready
    for its client. AgentStartError, TerminalStartError, OSError when it cannot."""
    started, output = launcher.start_terminal(settings, record, runs, start)
    proc = started.process
    assert isinstance(proc, subprocess.Popen)
    lines = sandbox_process.follow(proc, output)
    try:
        said = await asyncio.wait_for(_until_ready(lines), READY_TIMEOUT)
    except TimeoutError:
        said = ["no answer"]
    except BaseException:
        proc.terminate()
        os.close(output)
        raise
    if said:
        proc.terminate()
        os.close(output)
        raise TerminalStartError("; ".join(said[-3:])[:300])
    conn = LiveConnection(
        id=started.connection_id,
        sandbox=started.spec.name,
        since=datetime.now(UTC),
        process=proc,
        egress_base=started.egress_base,
        terminal=runs,
    )
    record.connections[conn.id] = conn
    registry.touch(record)
    task = asyncio.create_task(_follow(record, registry, conn, lines, output))
    _followed.add(task)
    task.add_done_callback(_followed.discard)
    attach = sandbox_process.attach_command(started.spec.name)
    return TerminalStarted(sandbox=started.spec.name, attach=attach)


async def _until_ready(lines: AsyncIterator[str]) -> list[str]:
    """[] once the sandbox is ready, else what its launcher said before it ended."""
    said = []
    async for line in lines:
        if line == READY_LINE:
            return []
        said.append(line)
    return said or ["the sandbox ended"]


async def _follow(
    record: AgentRecord,
    registry: AgentRegistry,
    conn: LiveConnection,
    lines: AsyncIterator[str],
    output: int,
) -> None:
    """Its logs and egress events until the launcher ends (handlerd stopping: it goes on alone)."""

    def on_egress(event: dict[str, str]) -> None:
        registry.add_event(record, conn.id, event)

    try:
        async for line in lines:
            sandbox_process.log_line(line, conn.id, on_egress)
        log.info("[%s] terminal ended (exit %s)", conn.id, conn.process.returncode)
    finally:
        with contextlib.suppress(OSError):
            os.close(output)
        record.connections.pop(conn.id, None)
