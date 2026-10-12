// Hash router:
//   #/                   projects (home)
//   #/projects/new[?knowledge=:path]      a new project, optionally with a knowledge folder
//   #/projects/:id                        a project: start a session with a request, its sessions
//   #/projects/:id/edit                   a project's settings
//   #/projects/:id/agents/new · #/projects/:id/agents/:agent   an agent of a project
//   #/sessions/:key      a chat session of the sidebar
//   #/terminals/:agent/:connection   a terminal (`handler terminal`, D.16) of an agent: its network
//   #/agents             ad-hoc agents (no project)
//   #/agents/:id         an agent (of a project or not): start a session or a run, its sessions
//   #/agents/new[?builtin=:name] · #/agents/:id/edit   an ad-hoc agent's settings (a new one; set up a built-in agent)
//   #/runs/:id           a run of an agent with an interface (D.18): its input and result
//   #/settings[/:section]  settings, one page per section (lib/settings.ts): model access by default
//   #/skills · #/skills/:name[?imported=new|replaced] · #/skills/new   the skill library (D.17); a
//                        skill, its editor (just imported: what to do next; a new one)
//   #/apps               mini apps: register, deploy, open, roll back (docs/dev/design/miniapps.md)
//   #/automations · #/automations/:name   automations (I): the list; one's permissions, files, runs
//   #/automations/new[?agent=:id] · #/automations/:name/edit   the automation form (I.1): a new one
//                        (for that agent), or one it can say, changed
//   #/inbox              what handler told you: apps' notifications, automations' results
//   #/knowledge[?path=:folder][&note=:file]   the knowledge root: settings, folders, notes (D.5)

import { SETTINGS_SECTIONS, type SettingsSection } from "./settings";

export type Route =
  | { view: "home" }
  | { view: "project"; id: string }
  | { view: "edit-project"; id?: string; knowledge?: string } // no id: a new one
  | { view: "edit-agent"; project: string; id?: string; from?: string } // no id: a new one, a copy of `from`
  | { view: "session"; key: string }
  | { view: "terminal"; agent: string; connection: string }
  | { view: "agents" }
  | { view: "agent"; id: string }
  | { view: "edit-ad-hoc"; id?: string; builtin?: string } // no id: a new one; `builtin`: setting it up (D.18)
  | { view: "run"; id: string }
  | { view: "settings"; section: SettingsSection }
  | { view: "skills" }
  | { view: "skill"; name: string | null; imported?: Imported } // null: a new one
  | { view: "apps" }
  | { view: "automations" }
  | { view: "automation"; name: string }
  | { view: "edit-automation"; name?: string; agent?: string } // no name: a new one
  | { view: "inbox" }
  | { view: "knowledge"; path?: string; note?: string };

// a skill just imported to the library: a new one, or one whose files it replaced
export type Imported = "new" | "replaced";

export function parse(hash: string): Route {
  const [path = "", query = ""] = hash.replace(/^#\/?/, "").split("?");
  const [first = "", second, third] = path.split("/");
  const id = second ? decodeURIComponent(second) : "";
  const params = new URLSearchParams(query);
  if (first === "sessions" && id) return { view: "session", key: id };
  if (first === "runs" && id) return { view: "run", id };
  if (first === "terminals" && id && third) return { view: "terminal", agent: id, connection: decodeURIComponent(third) };
  if (first === "agents" && id === "new") {
    const builtin = params.get("builtin");
    return builtin ? { view: "edit-ad-hoc", builtin } : { view: "edit-ad-hoc" };
  }
  if (first === "agents" && id && third === "edit") return { view: "edit-ad-hoc", id };
  if (first === "agents" && id) return { view: "agent", id };
  if (first === "agents") return { view: "agents" };
  if (first === "skills" && id === "new") return { view: "skill", name: null };
  if (first === "skills" && id) {
    const imported = params.get("imported");
    return imported === "new" || imported === "replaced" ? { view: "skill", name: id, imported } : { view: "skill", name: id };
  }
  if (first === "skills") return { view: "skills" };
  if (first === "settings") {
    const section = SETTINGS_SECTIONS.find((s) => s.id === id)?.id ?? "models";
    return { view: "settings", section };
  }
  if (first === "projects" && id === "new") {
    const knowledge = params.get("knowledge");
    return knowledge ? { view: "edit-project", knowledge } : { view: "edit-project" };
  }
  if (first === "projects" && id && third === "edit") return { view: "edit-project", id };
  if (first === "projects" && id && third === "agents") {
    const agent = path.split("/")[3];
    if (agent && agent !== "new") return { view: "edit-agent", project: id, id: decodeURIComponent(agent) };
    const from = params.get("from");
    return from ? { view: "edit-agent", project: id, from } : { view: "edit-agent", project: id };
  }
  if (first === "projects" && id) return { view: "project", id };
  if (first === "apps") return { view: "apps" };
  if (first === "automations" && id === "new") {
    const agent = params.get("agent");
    return agent ? { view: "edit-automation", agent } : { view: "edit-automation" };
  }
  if (first === "automations" && id && third === "edit") return { view: "edit-automation", name: id };
  if (first === "automations" && id) return { view: "automation", name: id };
  if (first === "automations") return { view: "automations" };
  if (first === "inbox") return { view: "inbox" };
  if (first === "knowledge") {
    const path = params.get("path");
    const note = params.get("note");
    return { view: "knowledge", ...(path ? { path } : {}), ...(note ? { note } : {}) };
  }
  return { view: "home" };
}

export const router = $state({ route: parse(typeof window === "undefined" ? "" : window.location.hash) });

// a page with unsaved changes (the skill editor) says so here: leaving it asks first
export const leaving = { unsaved: false };
let shown = typeof window === "undefined" ? "" : window.location.hash;

export function startRouter(): void {
  window.addEventListener("hashchange", () => {
    if (leaving.unsaved && !confirm("Leave without saving your changes?")) {
      history.replaceState(null, "", shown || "#/");
      return;
    }
    leaving.unsaved = false;
    shown = window.location.hash;
    router.route = parse(shown);
  });
}

export function href(route: Route): string {
  switch (route.view) {
    case "home":
      return "#/";
    case "project":
      return `#/projects/${encodeURIComponent(route.id)}`;
    case "edit-project":
      if (route.id) return `#/projects/${encodeURIComponent(route.id)}/edit`;
      return route.knowledge ? `#/projects/new?knowledge=${encodeURIComponent(route.knowledge)}` : "#/projects/new";
    case "edit-agent":
      if (route.id) return `#/projects/${encodeURIComponent(route.project)}/agents/${encodeURIComponent(route.id)}`;
      return `#/projects/${encodeURIComponent(route.project)}/agents/new${route.from ? `?from=${encodeURIComponent(route.from)}` : ""}`;
    case "session":
      return `#/sessions/${encodeURIComponent(route.key)}`;
    case "terminal":
      return `#/terminals/${encodeURIComponent(route.agent)}/${encodeURIComponent(route.connection)}`;
    case "agents":
      return "#/agents";
    case "agent":
      return `#/agents/${encodeURIComponent(route.id)}`;
    case "edit-ad-hoc":
      if (route.id) return `#/agents/${encodeURIComponent(route.id)}/edit`;
      return route.builtin ? `#/agents/new?builtin=${encodeURIComponent(route.builtin)}` : "#/agents/new";
    case "run":
      return `#/runs/${encodeURIComponent(route.id)}`;
    case "settings":
      return `#/settings/${route.section}`;
    case "skills":
      return "#/skills";
    case "skill":
      if (route.name === null) return "#/skills/new";
      return `#/skills/${encodeURIComponent(route.name)}${route.imported ? `?imported=${route.imported}` : ""}`;
    case "apps":
      return "#/apps";
    case "automations":
      return "#/automations";
    case "automation":
      return `#/automations/${encodeURIComponent(route.name)}`;
    case "edit-automation":
      if (route.name) return `#/automations/${encodeURIComponent(route.name)}/edit`;
      return route.agent ? `#/automations/new?agent=${encodeURIComponent(route.agent)}` : "#/automations/new";
    case "inbox":
      return "#/inbox";
    case "knowledge": {
      const params = new URLSearchParams();
      if (route.path) params.set("path", route.path);
      if (route.note) params.set("note", route.note);
      const query = params.toString();
      return query ? `#/knowledge?${query}` : "#/knowledge";
    }
  }
}

/** Go to `route`; `replace` keeps the current entry out of the history (for action routes). */
export function navigate(route: Route, replace = false): void {
  if (replace) {
    shown = href(route);
    history.replaceState(null, "", shown);
    router.route = route;
  } else {
    window.location.hash = href(route);
  }
}
