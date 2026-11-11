"""What uses what (D.22): every link between the things Handler keeps, in one place, computed
from them each time (nothing stored). A link is (user, used, how):

    an agent      picks a skill, reads a knowledge folder, uses an addon, runs on an account or
                  a provider
    a project     gives a skill or an addon to all its agents (each of them then uses it too)
    an automation runs an agent, runs when an agent's sessions stop, appends to notes of a
                  knowledge folder
    an app        is given an agent for one of its needs
    Handler       uses the agent given for one of its needs (the skill reviewer…, D.18)

Uses of a thing are the links where it is the user; its used-by, where it is the used. Clients
show both.
"""

import os
from dataclasses import dataclass
from pathlib import PurePosixPath

from handler_contracts import UseKind, UseRef, Uses

from . import handler_needs, knowledge
from .agents import AgentRecord
from .apps import AppStore
from .automations import Automations
from .projects import ProjectRegistry
from .settings import Settings


@dataclass(frozen=True)
class Link:
    user: UseRef  # its `how` unused
    used: UseRef
    how: str  # what the user does with it, from the user's side: "picks it"


class UseGraph:
    def __init__(
        self,
        settings: Settings,
        projects: ProjectRegistry,
        automations: Automations,
        apps: AppStore,
    ) -> None:
        self.settings, self.projects = settings, projects
        self.automations, self.apps = automations, apps

    def of(self, kind: UseKind, ident: str) -> Uses:
        links = self.links()
        uses = [
            ln.used.model_copy(update={"how": ln.how}) for ln in links if same(ln.user, kind, ident)
        ]
        used_by = [
            ln.user.model_copy(update={"how": ln.how}) for ln in links if same(ln.used, kind, ident)
        ]
        return Uses(uses=dedupe(uses), used_by=dedupe(used_by))

    def links(self) -> list[Link]:
        found: list[Link] = []
        agents = list(self.projects.registry.agents.values())
        for agent in agents:
            found += self.agent_links(agent)
        for project in self.projects.projects.values():
            ref = UseRef(kind="project", id=project.id, label=project.name, how="")
            for skill in project.skills:
                found.append(Link(ref, thing("skill", skill), "gives it to all its agents"))
            for use in project.addons:
                found.append(Link(ref, thing("addon", use.addon), "gives it to all its agents"))
        found += self.automation_links()
        for app in self.apps.views():
            ref = UseRef(kind="app", id=app.name, label=app.name, how="")
            for need in app.agents:
                if need.agent_id and (agent := self.projects.registry.get(need.agent_id)):
                    how = f"needs it: {need.description or need.name}"
                    found.append(Link(ref, self.agent_ref(agent), how))
        given = handler_needs.given(self.settings.state_dir)
        for need in handler_needs.load_all():
            agent_id = given.get(need.name)
            if agent_id and (agent := self.projects.registry.get(agent_id)):
                ref = UseRef(kind="handler", id=need.name, label="Handler", how="")
                how = f"its {need.definition.agent_name.lower()}"
                found.append(Link(ref, self.agent_ref(agent), how))
        return found

    def automation_links(self) -> list[Link]:
        found: list[Link] = []
        for view in self.automations.views():
            ref = UseRef(kind="automation", id=view.name, label=view.name, how="")
            if view.agent_id and (agent := self.projects.registry.get(view.agent_id)):
                found.append(Link(ref, self.agent_ref(agent), "runs it"))
            for agent_id in view.only_agents:
                if agent := self.projects.registry.get(agent_id):
                    found.append(Link(ref, self.agent_ref(agent), "runs when its sessions stop"))
            for append in view.definition.append if view.definition else []:
                folder = str(PurePosixPath(append.to).parent)
                found.append(Link(ref, thing("knowledge", folder), f"appends to {append.to}"))
        return found

    def agent_links(self, agent: AgentRecord) -> list[Link]:
        me = self.agent_ref(agent)
        found = [Link(me, thing("skill", s), "picks it") for s in agent.skills]
        found += [Link(me, thing("skill", s), "given by its project") for s in agent.project_skills]
        reads = "puts it into each call" if agent.model_alone else "reads it"
        found += [Link(me, thing("knowledge", k), reads) for k in agent.knowledge]
        found += [Link(me, thing("addon", u.addon), "uses it") for u in agent.addons]
        given = "given by its project"
        found += [Link(me, thing("addon", u.addon), given) for u in agent.project_addons]
        if (m := agent.model).account:
            found.append(Link(me, thing("account", m.account), "runs on it"))
        elif m.provider:
            found.append(Link(me, thing("provider", m.provider), "runs on it"))
        return found

    def agent_ref(self, agent: AgentRecord) -> UseRef:
        project = self.projects.get(agent.project_id or "")
        name = agent.name or (os.path.basename(agent.scope) if agent.scope else agent.id)
        label = f"{project.name} · {name}" if project else name
        return UseRef(kind="agent", id=agent.id, label=label, how="")


def thing(kind: UseKind, ident: str) -> UseRef:
    """A thing known by its name (a knowledge folder by its path in the root: "." the root)."""
    label = knowledge.mount_name("knowledge", ident) if kind == "knowledge" else ident
    return UseRef(kind=kind, id=ident, label=label, how="")


def same(ref: UseRef, kind: UseKind, ident: str) -> bool:
    """`ref` is that thing; a knowledge folder also stands for the folders in it."""
    if ref.kind != kind:
        return False
    inside = kind == "knowledge" and (ident == "." or ref.id.startswith(ident + "/"))
    return ref.id == ident or inside


def dedupe(refs: list[UseRef]) -> list[UseRef]:
    """Once each (the same thing used two ways: both said), by kind then label."""
    seen: dict[tuple[str, str], UseRef] = {}
    for r in refs:
        key = (r.kind, r.id)
        if key in seen and r.how not in seen[key].how:
            seen[key] = seen[key].model_copy(update={"how": f"{seen[key].how}; {r.how}"})
        seen.setdefault(key, r)
    return sorted(seen.values(), key=lambda r: (r.kind, r.label.lower()))
