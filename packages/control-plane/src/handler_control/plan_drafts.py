"""Plan drafts (D.27): a plan being written, kept by Handler in its state, never in a folder of
yours; written by a plan builder's session (one of Handler's helpers) seeing the project
read-only, or edited by hand; approved into a plan (plans.py), a new one each time.

    <state>/plan-drafts/<id>/draft.json    what it is for: its project and folder, its builder
                                           session (Handler's: never mounted)
                             draft/plan.md  its text: `draft/` is its builder session's folder,
                                            the only one of Handler's it gets, read-write

    builder_problems  why an agent cannot build plans: the builder gets no addon (no binding, no
                      secret but its model's) and a network reaching only its model's sites
                      (`plan.builder-has-no-secret`)
    brief             what a builder's session is told: the project, its draft, the runners
"""

import contextlib
import hashlib
import json
import os
import secrets
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from handler_contracts import PlanDraft

from . import session_files
from .agents import AgentRecord
from .files import write_private
from .launcher import plan_drafts_root
from .plans import TITLE, Source
from .projects import ProjectRegistry
from .settings import Settings

TEXT = "plan.md"
MAX_BYTES = 256 * 1024  # as a plan file's


class DraftError(Exception):
    """A draft request refused: its HTTP status, and why."""

    def __init__(self, status: int, title: str, detail: str | None = None) -> None:
        super().__init__(detail or title)
        self.status = status
        self.title = title
        self.detail = detail


def builder_problems(agent: AgentRecord) -> list[str]:
    """Why `agent` cannot build a plan (`plan.builder-has-no-secret`): it only writes a draft, so
    it gets no folder of its own (each session works on a draft), no addon (no binding, no secret
    but its model's), and a network reaching only its model's sites: filtered, enforced, no host
    of its own (or none)."""
    name = agent.name or agent.id
    if agent.app is not None or agent.chat:
        return [f"{name} is not one of Handler's helpers"]
    if agent.model_alone:
        return [f"{name} is the model alone: a plan builder reads the project, in a sandbox"]
    found = []
    if agent.scope is not None:
        found.append(f"{name} has a folder: a plan builder's sessions each work on a draft")
    if agent.addon_uses:
        found.append(f"{name} has tools: a plan builder gets no connection and no secret")
    only_its_model = agent.network == "filtered" and agent.egress == "enforce" and not agent.allow
    if not only_its_model and agent.network != "none":
        found.append(f"{name}'s network reaches more than its model's sites")
    return found


def brief(folder: str, draft: Path, runners: list[str]) -> str:
    """What a builder's session is told, after its agent's instructions: where the project and
    its draft are, and which agents may run the plan's steps."""
    if runners:
        names = ", ".join(runners)
        agents = (
            f"The agents of this project that may run its steps: {names}. Name one in `Agent:` "
            "(ask the user when several may)."
        )
    else:
        agents = (
            "No agent of this project may run its steps yet: leave `Agent:` out; the user "
            "creates one when reviewing the plan."
        )
    return (
        "## This session's brief\n\n"
        f"You are Handler's plan builder. The project is {folder}: you see it read-only. Your "
        f"draft is {draft}: write the plan in {draft / TEXT}, nowhere else. The plan's steps "
        f"will work in {folder}. {agents}"
    )


class PlanDrafts:
    def __init__(self, settings: Settings, projects: ProjectRegistry) -> None:
        self.projects = projects
        self.root = plan_drafts_root(settings)

    def folder(self, draft_id: str) -> Path:
        """Its builder session's folder, where its text is."""
        self.meta(draft_id)
        return self.root / draft_id / "draft"

    def meta(self, draft_id: str) -> dict[str, Any]:
        try:
            return json.loads((self.root / draft_id / "draft.json").read_text())
        except (FileNotFoundError, NotADirectoryError):
            raise DraftError(404, "no such draft", draft_id) from None

    def ids(self) -> list[str]:
        return [p.parent.name for p in self.root.glob("*/draft.json")]

    def create(self, project_id: str, text: str = "", from_plan: str | None = None) -> PlanDraft:
        """A new draft for the project: empty, or a copy of an approved plan's text."""
        project = self.projects.get(project_id)
        if project is None:
            raise DraftError(404, "no such project", project_id)
        draft_id = "d_" + secrets.token_hex(8)
        folder = self.root / draft_id / "draft"
        folder.mkdir(mode=0o700, parents=True)
        self.root.chmod(0o700)
        (self.root / draft_id).chmod(0o700)
        write_private(folder / TEXT, text)  # a new folder: nothing there to follow yet
        meta = {
            "id": draft_id,
            "projectId": project.id,
            "folder": project.folder,
            "createdAt": datetime.now(UTC).isoformat(),
            "sessionId": None,
            "fromPlan": from_plan,
        }
        write_private(self.root / draft_id / "draft.json", json.dumps(meta, indent=2))
        return self.get(draft_id)

    def source(self, draft_id: str) -> Source:
        """Where its text is read from, to review and approve it; its steps work in its project's
        folder."""
        meta = self.meta(draft_id)
        return Source(self.folder(draft_id), TEXT, meta["folder"], draft_id=draft_id)

    def read(self, draft_id: str) -> tuple[bytes, int]:
        """Its text (its first bytes, its size), read as a session's folder is: no link followed,
        whatever its builder left there (`plan.read-without-following-links`)."""
        return session_files.read_bytes(self.folder(draft_id), TEXT)

    def get(self, draft_id: str) -> PlanDraft:
        meta = self.meta(draft_id)
        title, digest, changed = None, hashlib.sha256(b"").hexdigest(), meta["createdAt"]
        with contextlib.suppress(session_files.PathError, OSError):
            data, size = self.read(draft_id)
            digest = hashlib.sha256(data).hexdigest()
            if size <= MAX_BYTES:
                title = _title(data)
            st = os.stat(self.folder(draft_id) / TEXT, follow_symlinks=False)
            changed = datetime.fromtimestamp(st.st_mtime, UTC).isoformat()
        return PlanDraft(
            id=meta["id"],
            project_id=meta["projectId"],
            folder=meta["folder"],
            title=title,
            digest=digest,
            created_at=datetime.fromisoformat(meta["createdAt"]),
            changed_at=datetime.fromisoformat(changed),
            session_id=meta["sessionId"],
            from_plan=meta["fromPlan"],
        )

    def list(self, project_id: str | None = None) -> list[PlanDraft]:
        """The most recently changed first."""
        drafts = [self.get(i) for i in self.ids()]
        drafts = [d for d in drafts if project_id is None or d.project_id == project_id]
        return sorted(drafts, key=lambda d: d.changed_at, reverse=True)

    def save(self, draft_id: str, text: str, digest: str) -> PlanDraft:
        """Its text edited by hand, over the one read (`plan.a-draft-is-not-a-plan`): refused when
        it changed since (its builder wrote). Written to a new file renamed over plan.md, never
        through a link its builder left (`plan.builder-reads-the-project-only`)."""
        if self.get(draft_id).digest != digest:
            raise DraftError(
                409, "the draft changed since you read it", "read it again, then edit it"
            )
        folder = self.folder(draft_id)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".plan-", suffix=".md")  # O_EXCL, 0600
        try:
            with os.fdopen(fd, "w") as f:
                f.write(text)
            os.replace(tmp, folder / TEXT)  # replaces a link itself, never its target
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise
        return self.get(draft_id)

    def started(self, draft_id: str, session_id: str) -> None:
        """Its builder session, once started: one per draft."""
        meta = self.meta(draft_id) | {"sessionId": session_id}
        write_private(self.root / draft_id / "draft.json", json.dumps(meta, indent=2))

    def delete(self, draft_id: str) -> None:
        """Thrown away: its folder goes (its sessions stay)."""
        self.meta(draft_id)
        shutil.rmtree(self.root / draft_id)  # never follows a link it holds


def _title(data: bytes) -> str | None:
    """Its `# Plan:` line's title, when its text starts with one."""
    for line in data.decode(errors="replace").splitlines():
        if line.strip():
            m = TITLE.match(line)
            return (m.group(1) or None) if m else None
    return None
