"""What every route module shares: problem details (RFC 9457), dumping contract models, parsing
bodies, mapping domain errors, and the Context every route gets."""

import contextlib
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError

from handler_contracts import (
    Agent,
    AgentModel,
    Connection,
    Problem,
    Project,
    acp_path,
)

from .. import (
    auth,
    checks,
    contexts,
    knowledge,
    launcher,
)
from ..agents import (
    AgentRecord,
    AgentRegistry,
    RunsAs,
)
from ..apps import AppStore
from ..automations import Automations
from ..builds import (
    BuildStore,
)
from ..image_updates import ImageUpdater
from ..inbox import Inbox
from ..projects import ProjectRecord, ProjectRegistry
from ..remote import Connector
from ..sessions import SessionRecord, SessionStore
from ..settings import Settings

log = logging.getLogger("handler.api")


class ProblemError(Exception):
    def __init__(self, status: int, title: str, detail: str | None = None) -> None:
        super().__init__(title)
        self.problem = Problem(title=title, status=status, detail=detail)


def dump(model: BaseModel | list[Any], status: int = 200) -> JSONResponse:
    def one(m: BaseModel) -> Any:
        return m.model_dump(mode="json", by_alias=True, exclude_none=True)

    content = [one(m) for m in model] if isinstance(model, list) else one(model)
    return JSONResponse(content, status_code=status)


@dataclass
class Context:
    """What every route needs: settings, the token, the agent registry."""

    settings: Settings
    token: str
    registry: AgentRegistry
    projects: ProjectRegistry
    sessions: SessionStore
    builds: BuildStore
    remote: Connector
    apps: AppStore
    updates: ImageUpdater
    automations: Automations
    inbox: Inbox

    def require_auth(self, request: Request) -> None:
        """HTTP auth (invariant 5): allowed Origin (if any) and the bearer token."""
        if not auth.origin_allowed(request.headers.get("origin"), self.settings.allowed_origins):
            raise ProblemError(403, "origin not allowed")
        presented = auth.bearer_from_header(request.headers.get("authorization"))
        if not auth.token_matches(presented, self.token):
            raise ProblemError(401, "missing or invalid token")

    def get_session(self, session_id: str) -> SessionRecord:
        record = self.sessions.records.get(session_id)
        if record is None:
            raise ProblemError(404, "session not found", session_id)
        return record

    def get_agent(self, agent_id: str) -> AgentRecord:
        record = self.registry.get(agent_id)
        if record is None:
            raise ProblemError(404, "agent not found", agent_id)
        return record

    def get_project(self, project_id: str) -> ProjectRecord:
        project = self.projects.get(project_id)
        if project is None:
            raise ProblemError(404, "project not found", project_id)
        return project

    def get_project_agent(self, project: ProjectRecord, agent_id: str) -> AgentRecord:
        record = self.registry.get(agent_id)
        if record is None or record.project_id != project.id:
            raise ProblemError(404, "agent not found", agent_id)
        return record

    def to_project(self, p: ProjectRecord) -> Project:
        return Project(
            id=p.id,
            name=p.name,
            description=p.description,
            folder=p.folder,
            default_agent=p.default_agent,
            caches=p.caches,
            context=p.context,
            agents=[self.to_agent(a) for a in self.projects.agents(p)],
            created_at=p.created_at,
            last_used_at=self.projects.last_used(p),
        )

    def to_agent(self, r: AgentRecord) -> Agent:
        """An agent as seen by clients, with, for each of its models, the hosts a session with
        it requires *now* (its account or provider, the agent's tools), or why it cannot start."""
        connections = [
            Connection(id=c.id, sandbox=c.sandbox, since=c.since, terminal=c.terminal)
            for c in list(r.connections.values())
        ]
        return Agent.model_validate(
            r.model_dump()
            | {
                "models": [self.to_agent_model(r, m) for m in r.models],
                "egress": r.egress if r.network == "filtered" else None,
                "acp_url": self.settings.base_url.replace("http://", "ws://") + acp_path(r.id),
                "connections": connections,
            }
        )

    def to_agent_model(self, r: AgentRecord, runs: RunsAs) -> AgentModel:
        required, problem = [], None
        try:
            contexts.check(self.settings.sources, r.context, runs.account, runs.provider)
            resolved = launcher.agent_spec(self.settings, runs)
            if r.network == "filtered":
                required = launcher.required_hosts(self.settings, resolved, r)
        except (contexts.ContextError, launcher.AgentStartError) as e:
            problem = str(e)
        return AgentModel(**runs.model_dump(), problem=problem, required_hosts=required)


def add_error_handlers(app: FastAPI) -> None:
    def problem_response(problem: Problem) -> Response:
        body = problem.model_dump_json(exclude_none=True)
        return Response(body, status_code=problem.status, media_type="application/problem+json")

    @app.exception_handler(ProblemError)
    async def _problem(_: Request, e: ProblemError) -> Response:
        return problem_response(e.problem)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, e: RequestValidationError) -> Response:
        return problem_response(
            Problem(title="invalid request", status=422, detail=str(e.errors()))
        )


def text_or_none(value: str | None) -> str | None:
    return (value or "").strip() or None


@contextlib.contextmanager
def check_problems() -> Iterator[None]:
    """The rules an agent or a project must pass (checks.py) → 403 (forbidden), 409 (conflict),
    400 (anything else)."""
    try:
        yield
    except checks.ForbiddenError as e:
        raise ProblemError(403, e.title, str(e)) from None
    except checks.ConflictError as e:
        raise ProblemError(409, e.title, str(e)) from None
    except checks.CheckError as e:
        raise ProblemError(400, e.title, str(e)) from None


@contextlib.contextmanager
def knowledge_problems() -> Iterator[None]:
    """KnowledgeError → 409 when it conflicts with the current state, 400 otherwise (D.5)."""
    try:
        yield
    except knowledge.KnowledgeConflictError as e:
        raise ProblemError(409, "knowledge conflict", str(e)) from None
    except knowledge.KnowledgeError as e:
        raise ProblemError(400, "knowledge unusable", str(e)) from None


def parse_body[M: BaseModel](model: type[M], raw: bytes) -> M:
    try:
        return model.model_validate_json(raw)
    except ValidationError as e:
        raise ProblemError(422, "invalid request", str(e)) from None
