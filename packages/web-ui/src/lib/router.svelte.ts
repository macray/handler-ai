// Hash router:
//   #/                   projects (home)
//   #/projects/new[?knowledge=:path][?folder=:path]   a new project, optionally with a knowledge folder,
//                                                   or on a folder (an app's data: H.2)
//   #/projects/:id[?agent=:agent]         a project: its agents, the chosen one's start and sessions
//   #/projects/:id/edit                   a project's settings
//   #/projects/:id/agents/new · #/projects/:id/agents/:agent   an agent of a project
//   #/sessions/:key      a chat session of the sidebar
//   #/terminals/:agent/:connection   a terminal (`handler terminal`, D.16) of an agent: its network
//   #/agents[?agent=:agent]   outside projects: the agents of no project, the chosen one's start and sessions
//   #/agents/:id         an agent, wherever it is: its place (its project's page, or outside projects) with it chosen
//   #/agents/new[?app=:app&need=:need] · #/agents/:id/edit   an ad-hoc agent's settings (a new one;
//                                                     or an app's need set up from its definition)
//   #/runs/:id           a run of an agent with an interface (D.18): its input and result
//   #/settings[/:section]  settings, one page per section (lib/settings.ts): model access by default
//   #/addons[?install=:source]   the addons and their configurations (G, D.15), in the library
//                        (install: that source's preview open, G.5)
//   #/discover · #/discover/:source/:kind/:name   what the sources offer (D.26); an item's page
//                        (kind: apps, agents, addons)
//   #/skills · #/skills/:name[?imported=new|replaced] · #/skills/new   the skill library (D.17); a
//                        skill, its editor (just imported: what to do next; a new one)
//   #/apps               apps: yours, Handler's to install, making one (docs/dev/design/apps.md)
//   #/apps/:name         an app's page: open, what it needs and may touch, deploy, roll back
//   #/apps/:name/install   installing one, on one page
//   #/automations · #/automations/:name   automations (I): the list; one's permissions, files, runs
//   #/automations/new[?agent=:id] · #/automations/:name/edit   the automation form (I.1): a new one
//                        (for that agent), or one it can say, changed
//   #/ask                Ask: say what you want, Handler picks the app's ask that does it (D.24)
//   #/inbox              what handler told you: apps' notifications, automations' results
//   #/knowledge[?path=:folder][&note=:file]   the knowledge root: settings, folders, notes (D.5)
//   #/setup/:file[?project=:id]   the agents of an agents file being imported set up (D.23),
//                        into that project
//   #/helpers/:need/set-up   an agent set up for one of Handler's needs (D.18), then given to it

import { SETTINGS_SECTIONS, type SettingsSection } from "./settings";

export type Route =
  | { view: "home" }
  | { view: "ask" }
  | { view: "chat"; agent?: string; say?: string; new?: boolean } // agent: who you talk to; say: the first message, typed (Ask's "Start a chat about it"); new: someone new
  | { view: "project"; id: string; agent?: string } // agent: the one chosen (else its default)
  | { view: "edit-project"; id?: string; knowledge?: string; folder?: string } // no id: a new one
  | { view: "edit-agent"; project: string; id?: string; from?: string } // no id: a new one, a copy of `from`
  | { view: "session"; key: string }
  | { view: "terminal"; agent: string; connection: string }
  | { view: "agents"; agent?: string } // outside projects; agent: the one chosen
  | { view: "agent"; id: string }
  | { view: "edit-ad-hoc"; id?: string; app?: string; need?: string } // no id: a new one; an app's `need`: setting it up (H.2)
  | { view: "run"; id: string }
  | { view: "settings"; section: SettingsSection }
  | { view: "skills" }
  | { view: "addons"; install?: string } // install: the preview of `source:<source>/<name>` open
  | { view: "discover" }
  | { view: "discover-item"; source: string; kind: "apps" | "agents" | "addons"; name: string }
  | { view: "skill"; name: string | null; imported?: Imported } // null: a new one
  | { view: "apps"; app?: string } // `app`: that app's page
  | { view: "install-app"; name: string }
  | { view: "automations" }
  | { view: "automation"; name: string }
  | { view: "edit-automation"; name?: string; agent?: string } // no name: a new one
  | { view: "inbox" }
  | { view: "knowledge"; path?: string; note?: string }
  | { view: "setup"; file: string; project?: string } // an agents file's agents set up (D.23)
  | { view: "set-up-helper"; need: string }; // an agent set up for one of Handler's needs (D.18)

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
    const app = params.get("app");
    const need = params.get("need");
    return app && need ? { view: "edit-ad-hoc", app, need } : { view: "edit-ad-hoc" };
  }
  if (first === "agents" && id && third === "edit") return { view: "edit-ad-hoc", id };
  if (first === "agents" && id) return { view: "agent", id };
  if (first === "agents") {
    const agent = params.get("agent");
    return agent ? { view: "agents", agent } : { view: "agents" };
  }
  if (first === "skills" && id === "new") return { view: "skill", name: null };
  if (first === "skills" && id) {
    const imported = params.get("imported");
    return imported === "new" || imported === "replaced" ? { view: "skill", name: id, imported } : { view: "skill", name: id };
  }
  if (first === "skills") return { view: "skills" };
  if (first === "addons") {
    const install = params.get("install");
    return install ? { view: "addons", install } : { view: "addons" };
  }
  if (first === "discover") {
    const [, , kind, name] = path.split("/");
    if (id && (kind === "apps" || kind === "agents" || kind === "addons") && name) return { view: "discover-item", source: id, kind, name: decodeURIComponent(name) };
    return { view: "discover" };
  }
  if (first === "settings") {
    const section = SETTINGS_SECTIONS.find((s) => s.id === id)?.id ?? "models";
    return { view: "settings", section };
  }
  if (first === "projects" && id === "new") {
    const knowledge = params.get("knowledge");
    const folder = params.get("folder");
    return { view: "edit-project", ...(knowledge ? { knowledge } : {}), ...(folder ? { folder } : {}) };
  }
  if (first === "projects" && id && third === "edit") return { view: "edit-project", id };
  if (first === "projects" && id && third === "agents") {
    const agent = path.split("/")[3];
    if (agent && agent !== "new") return { view: "edit-agent", project: id, id: decodeURIComponent(agent) };
    const from = params.get("from");
    return from ? { view: "edit-agent", project: id, from } : { view: "edit-agent", project: id };
  }
  if (first === "projects" && id) {
    const agent = params.get("agent");
    return agent ? { view: "project", id, agent } : { view: "project", id };
  }
  if (first === "apps" && id && third === "install") return { view: "install-app", name: id };
  if (first === "apps") return id ? { view: "apps", app: decodeURIComponent(id) } : { view: "apps" };
  if (first === "automations" && id === "new") {
    const agent = params.get("agent");
    return agent ? { view: "edit-automation", agent } : { view: "edit-automation" };
  }
  if (first === "automations" && id && third === "edit") return { view: "edit-automation", name: id };
  if (first === "automations" && id) return { view: "automation", name: id };
  if (first === "automations") return { view: "automations" };
  if (first === "inbox") return { view: "inbox" };
  if (first === "ask") return { view: "ask" };
  if (first === "chat") {
    const agent = params.get("agent");
    const say = params.get("say");
    return { view: "chat", ...(agent ? { agent } : {}), ...(say ? { say } : {}), ...(params.get("new") ? { new: true } : {}) };
  }
  if (first === "setup" && id) {
    const project = params.get("project");
    return { view: "setup", file: id, ...(project ? { project } : {}) };
  }
  if (first === "helpers" && id && third === "set-up") return { view: "set-up-helper", need: id };
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
      return `#/projects/${encodeURIComponent(route.id)}${route.agent ? `?agent=${encodeURIComponent(route.agent)}` : ""}`;
    case "edit-project":
      if (route.id) return `#/projects/${encodeURIComponent(route.id)}/edit`;
      if (route.folder) return `#/projects/new?folder=${encodeURIComponent(route.folder)}`;
      return route.knowledge ? `#/projects/new?knowledge=${encodeURIComponent(route.knowledge)}` : "#/projects/new";
    case "edit-agent":
      if (route.id) return `#/projects/${encodeURIComponent(route.project)}/agents/${encodeURIComponent(route.id)}`;
      return `#/projects/${encodeURIComponent(route.project)}/agents/new${route.from ? `?from=${encodeURIComponent(route.from)}` : ""}`;
    case "session":
      return `#/sessions/${encodeURIComponent(route.key)}`;
    case "terminal":
      return `#/terminals/${encodeURIComponent(route.agent)}/${encodeURIComponent(route.connection)}`;
    case "agents":
      return route.agent ? `#/agents?agent=${encodeURIComponent(route.agent)}` : "#/agents";
    case "agent":
      return `#/agents/${encodeURIComponent(route.id)}`;
    case "edit-ad-hoc":
      if (route.id) return `#/agents/${encodeURIComponent(route.id)}/edit`;
      if (route.app && route.need) return `#/agents/new?app=${encodeURIComponent(route.app)}&need=${encodeURIComponent(route.need)}`;
      return "#/agents/new";
    case "run":
      return `#/runs/${encodeURIComponent(route.id)}`;
    case "settings":
      return `#/settings/${route.section}`;
    case "skills":
      return "#/skills";
    case "addons":
      return route.install ? `#/addons?install=${encodeURIComponent(route.install)}` : "#/addons";
    case "discover":
      return "#/discover";
    case "discover-item":
      return `#/discover/${encodeURIComponent(route.source)}/${route.kind}/${encodeURIComponent(route.name)}`;
    case "skill":
      if (route.name === null) return "#/skills/new";
      return `#/skills/${encodeURIComponent(route.name)}${route.imported ? `?imported=${route.imported}` : ""}`;
    case "apps":
      return route.app ? `#/apps/${encodeURIComponent(route.app)}` : "#/apps";
    case "install-app":
      return `#/apps/${encodeURIComponent(route.name)}/install`;
    case "automations":
      return "#/automations";
    case "automation":
      return `#/automations/${encodeURIComponent(route.name)}`;
    case "edit-automation":
      if (route.name) return `#/automations/${encodeURIComponent(route.name)}/edit`;
      return route.agent ? `#/automations/new?agent=${encodeURIComponent(route.agent)}` : "#/automations/new";
    case "inbox":
      return "#/inbox";
    case "ask":
      return "#/ask";
    case "chat": {
      const params = new URLSearchParams();
      if (route.agent) params.set("agent", route.agent);
      if (route.say) params.set("say", route.say);
      if (route.new) params.set("new", "1");
      const query = params.toString();
      return query ? `#/chat?${query}` : "#/chat";
    }
    case "knowledge": {
      const params = new URLSearchParams();
      if (route.path) params.set("path", route.path);
      if (route.note) params.set("note", route.note);
      const query = params.toString();
      return query ? `#/knowledge?${query}` : "#/knowledge";
    }
    case "setup":
      return `#/setup/${encodeURIComponent(route.file)}${route.project ? `?project=${encodeURIComponent(route.project)}` : ""}`;
    case "set-up-helper":
      return `#/helpers/${encodeURIComponent(route.need)}/set-up`;
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
