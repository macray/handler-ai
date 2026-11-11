"""The state handler keeps for an agent: the harness's own history and settings (contract E).

    <data>/agent-state/<agent id>/<harness>@<account|provider>/<slot>
                                        one folder per state slot of the harness: the slot
                                        itself, or, for a file, the folder holding only it
                                        (`<slot>/<slot>`, contract A.1)

Each agent keeps its own (a project's transcripts never reach another project), one per model it
runs with: the harness's and its login's (another harness never reads them). Every state slot of
the harness that is not a login file (the account's) and not the per-session history (the
daemon's) lives here, created empty at the first start. Logging in again is never needed for
it: the account brings the login.
"""

from pathlib import Path

from handler_contracts import HarnessDescriptor

from .agents import AgentRecord, RunsAs


def root(data_dir: Path, agent: AgentRecord, runs: RunsAs) -> Path:
    return data_dir / "agent-state" / agent.id / f"{runs.harness}@{runs.account or runs.provider}"


def owned_slots(descriptor: HarnessDescriptor) -> list[str]:
    """The slots kept here: not a login, not per-session."""
    return [
        name
        for name, slot in descriptor.state_slots.items()
        if not (slot.credential or slot.per_session)
    ]


def ensure(descriptor: HarnessDescriptor, folder: Path) -> None:
    """Create what the harness expects to find: a folder, or a file (the slot's `initial`, else
    `{}` for JSON, empty otherwise: an absent file cannot be bound into a container). Never
    rewritten once there."""
    for name in owned_slots(descriptor):
        slot = descriptor.state_slots[name]
        if slot.kind == "dir":
            (folder / name).mkdir(parents=True, mode=0o700, exist_ok=True)
            continue
        path = folder / name / name
        if not path.exists():
            path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            default = "{}\n" if slot.target.endswith(".json") else ""
            path.write_text(slot.initial if slot.initial is not None else default)
            path.chmod(0o600)
