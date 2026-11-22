"""An app's jobs (H.1) run by its Who works (H.2): who may run one, and what its run reaches.

A job's run is a session with no agent (F, H.11). Its model is the Who works the person chose for
the app, or for that job (rule app-job.runs-as-its-who-works); what it reaches is its
declaration's (its Can do): each files need it names at the path given to the app, read-only when
it reads it (rule app-job.reads-are-read-only), read-write when it writes it, that folder's own
`.git` read-only over it (the person's history); its hosts the network filter's allow-list; its
schemas the Library's (the app's joined it at deploy, D.29), with the knowledge tool.

It launches as an agent of no project would, through a stand-in AgentRecord nobody registers
(`stand_in`): its id `app-<name>` (agent ids are hex, never so), so its harness state is
`agent-state/app-<name>/<harness>@<access>/`, one per app, shared by its runs at once.
"""

import os

from handler_contracts import (
    AgentInterface,
    AppManifestJob,
    HostFolder,
    KnowledgeUse,
    WhoWorks,
)

from . import agent_state, compose, save_rules
from .agents import AgentRecord, CheckedSettings, RunsAs
from .app_runs import AppRunError
from .launcher import JobPlace
from .settings import Settings


def cannot_run(job: AppManifestJob, who: WhoWorks | None) -> str | None:
    """Why that Who works cannot run the job, None when it can (rule
    app-job.runs-as-its-who-works): nobody chosen yet, or the model alone for a job reaching
    folders, schemas or hosts (it has no sandbox: no files, no tools, no network)."""
    if who is None:
        return "nobody is chosen to run it: choose who works for the app"
    if who.program is None and (job.files or job.schemas or job.egress):
        return (
            "the model alone cannot run it: it reaches folders, schemas or hosts, which need "
            "a program"
        )
    return None


def runs_as(settings: Settings, who: WhoWorks) -> RunsAs:
    """The model a Who works runs with, checked as an agent's is (E1, D.18): its program on its
    account or provider, or the model alone on a provider; AppRunError 409 when it cannot run."""
    check = save_rules.checked_model_alone if who.program is None else save_rules.checked_model
    try:
        return check(settings, who.model_access)
    except save_rules.CheckError as e:
        raise AppRunError(409, f"who works: {e}") from None


def place(job: AppManifestJob, given: dict[str, str]) -> tuple[JobPlace, str]:
    """Where its run works, from the paths given to its files needs (`given`, need → path,
    checked by the app's store), and the section of its request naming them. The first folder
    of `worksIn` it writes is its folder (the session's, where it starts); the others, and a job
    working only in folders it reads, start in a folder of their own. A written folder's `.git`
    is mounted read-only over it: one that is a link or a file is refused (409), as for the app's
    backend (H.9). `writes`: the real path of each folder it writes (two needs given one folder,
    or a link to it, are one)."""
    for need in job.works_in:
        if not os.path.isdir(given[need]):
            raise AppRunError(409, f"worksIn {need}: {given[need]} is a file, not a folder")
    work = next((given[n] for n in job.works_in if job.files[n] == "write"), None)
    folders: list[HostFolder] = []
    lines: list[str] = []
    for need, access in job.files.items():
        path, write = given[need], access == "write"
        if path != work:
            folders.append(HostFolder(source=path, target=path, writable=write))
        git = os.path.join(path, ".git")
        if write and os.path.lexists(git):
            if not compose.real_folder(git):
                raise AppRunError(
                    409,
                    f"folder {need}: its .git is not a folder (a link or a worktree's file), so "
                    "it cannot be kept read-only: give another folder",
                )
            folders.append(HostFolder(source=git, target=git, writable=False))
        mode = "read-write" if write else "read-only"
        where = "; you work in it" if need in job.works_in else ""
        lines.append(f"- `{need}`: `{path}` ({mode}{where})")
    note = "## Folders\n\nThe folders you are given, each at its path:\n\n" + "\n".join(lines)
    # what it writes, by real path: its run takes its turn on each (rule
    # app-job.writers-of-a-folder-take-turns), never on a path inside one
    writes = sorted({os.path.realpath(given[n]) for n, a in job.files.items() if a == "write"})
    return JobPlace(work=work, folders=tuple(folders), writes=tuple(writes)), note if lines else ""


def stand_in(
    app: str, name: str, job: AppManifestJob, runs: RunsAs, instructions: str
) -> AgentRecord:
    """The agent a job's run launches as, never registered: its model the Who works', its
    instructions `jobs/<name>.md`, its form and result the job's, unattended (bypass); a
    filtered network allowing its hosts; its schemas, read, or written when it writes a
    folder."""
    access = "write" if "write" in job.files.values() else "read"
    settings = CheckedSettings(
        model=runs,
        scope=None,
        allow=list(job.egress),
        permissions="bypass",
        schemas=[KnowledgeUse(schema_id=i, access=access) for i in job.schemas],
        interface=AgentInterface(fields=job.fields, result=job.result, timeout_sec=job.timeout_sec),
        model_alone=runs.harness is None,
    )
    return AgentRecord.model_validate(
        settings.model_dump()
        | {"id": agent_state.APP + app, "name": f"{app}: {name}", "instructions": instructions}
    )
