// Hash router:
//   #/                   where you left off (the last page, kept in this browser), else Projects
//   #/projects           the projects (where Handler opens the first time, and the logo)
//   #/library[/:shelf][/more][?install=:source][?project=:id]   the Library: what you get and
//                        manage, a shelf each (apps, agents, tools, skills, notes, automations; apps
//                        by default), yours or what you can get more of (more: the sources' items,
//                        examples; install: a tool's preview open, G.5; project: the agents got are
//                        set up there, D.23)
//   #/library/tools/:name[?connect=1]   a tool: what it is, then your connections to it (G, D.15;
//                        connect: just installed, its first connection's form open)
//   #/projects/new[?folder=:path]   a new project,
//                                                   or on a folder (an app's data: H.2)
//   #/projects/:id[?agent=:agent]   a project's Sessions tab: its agents, the chosen one's box and sessions
//   #/projects/:id/(plans|automations|settings)   a project's other tabs
//   #/projects/:id/agents/new[?from=:agent[&job=1]|?plan=:review] · #/projects/:id/agents/:agent   an agent
//                        of a project (a new one: a copy of `from`, made a job with `job` and then
//                        run by a new automation; or a plan runner for the review page `plan`,
//                        back to it once saved)
//   #/sessions/:key      a chat session of the sidebar
//   #/terminals/:agent/:connection   a terminal (`handler terminal`, D.16) of an agent: its network
//   #/agents[?agent=:agent]   outside projects: the agents of no project, the chosen one's start and sessions
//   #/agents/:id         an agent, wherever it is: its place (its project's page, or outside projects) with it chosen
//   #/agents/new[?app=:app&need=:need] · #/agents/:id/edit   an ad-hoc agent's settings (a new one;
//                                                     or an app's need set up from its definition)
//   #/runs/:id           a run of an agent with an interface (D.18): its input and result
//   #/settings[/:section]  settings, one page per section (lib/settings.ts): model access by default
//   #/settings/helpers/:need   one of Handler's helpers (D.18): who works, what it can do, its
//                        instructions; its set-up card when none is given yet
//   #/tools              the Library's Tools shelf (its tools and your connections, G, D.15)
//   #/discover/:source/:kind/:name   an item a source offers (D.26), its page (kind: apps, agents,
//                        addons); what they offer is each shelf's Get more
//   #/skills · #/skills/:name[?imported=new|replaced] · #/skills/new   the skill library (D.17); a
//                        skill, its editor (just imported: what to do next; a new one)
//   #/apps               apps: yours, Handler's to install, making one (apps design)
//   #/apps/:name         an app's page: open, what it needs and may touch, deploy, roll back
//   #/apps/:name/install   installing one, on one page
//   #/automations · #/automations/:name   automations (I): the list; one's permissions, files, runs
//   #/automations/new[?agent=:id] · #/automations/:name/edit   the automation form (I.1): a new one
//                        (for that agent), or one it can say, changed
//   #/chat[?agent=:id&say=…&new=1] · #/chat/ask   Chat: Talk (who you talk to, with no folder) and
//                        Ask (say what you want, Handler picks the app's action that does it, D.24)
//   #/inbox              what handler told you: apps' notifications, automations' results
//   #/plans · #/plans/:id   plans (D.27): the list; one's steps, their state and sessions
//   #/plans/review?(draft=:id|(session=:id|agent=:id)&path=:file)[&runner=:id]   a plan read, a
//                        draft (editable) or a file of that folder: its steps, its problems, who
//                        runs it (runner: the one chosen), Approve and run
//   #/notes[?path=:folder][&note=:file]   the notes root: settings, folders, notes (D.5)
//   #/setup/:file[?project=:id]   the agents of an agents file being imported set up (D.23),
//                        into that project

import { SETTINGS_SECTIONS, type SettingsSection } from "./settings";

/** A plan reviewed: a draft, or a file in that session's (or agent's) folder; runner: the agent
 *  chosen to run it. */
export type ReviewRoute = { view: "review-plan"; draft?: string; path?: string; session?: string; agent?: string; runner?: string };

/** The Library's shelves: for you, then for your agents. */
export const LIBRARY_SHELVES = [
  { id: "apps", label: "Apps", for: "you" },
  { id: "agents", label: "Agents", for: "you" },
  { id: "tools", label: "Tools", for: "agents" },
  { id: "skills", label: "Skills", for: "agents" },
  { id: "notes", label: "Notes", for: "agents" },
  { id: "automations", label: "Automations", for: "agents" },
] as const;
export type LibraryShelf = (typeof LIBRARY_SHELVES)[number]["id"];

/** A project's tabs but the first (Sessions, its own address). */
export const PROJECT_TABS = ["plans", "automations", "settings"] as const;
export type ProjectTab = (typeof PROJECT_TABS)[number];

export type Route =
  | { view: "projects" }
  | { view: "library"; shelf: LibraryShelf; more?: boolean; install?: string; project?: string } // more: Get more; install: a tool's preview open; project: the agents got go there
  | { view: "tool"; name: string; connect?: boolean } // a tool and your connections to it; connect: its first one's form open (just installed)
  | { view: "chat"; agent?: string; say?: string; new?: boolean } // Chat's Talk tab. agent: who you talk to; say: the first message, typed (Ask's "Start a chat about it"); new: someone new
  | { view: "ask" } // Chat's Ask tab (#/chat/ask): say what you want, Handler picks the app's action that does it (D.24)
  | { view: "project"; id: string; agent?: string; tab?: ProjectTab } // agent: the one chosen (else its default); tab: another than Sessions
  | { view: "edit-project"; folder?: string } // a new project
  | { view: "edit-agent"; project: string; id?: string; from?: string; job?: boolean; plan?: ReviewRoute } // no id: a new one, a copy of `from` (job: made a job, then a new automation runs it), or a plan runner for that review
  | { view: "session"; key: string }
  | { view: "terminal"; agent: string; connection: string }
  | { view: "agents"; agent?: string } // outside projects; agent: the one chosen
  | { view: "agent"; id: string }
  | { view: "edit-ad-hoc"; id?: string; app?: string; need?: string } // no id: a new one; an app's `need`: setting it up (H.2)
  | { view: "run"; id: string }
  | { view: "settings"; section: SettingsSection; helper?: string }
  | { view: "skills" }
  | { view: "addons" }
  | { view: "discover-item"; source: string; kind: "apps" | "agents" | "addons"; name: string }
  | { view: "skill"; name: string | null; imported?: Imported } // null: a new one
  | { view: "apps"; app?: string } // `app`: that app's page
  | { view: "install-app"; name: string }
  | { view: "automations" }
  | { view: "automation"; name: string }
  | { view: "edit-automation"; name?: string; agent?: string } // no name: a new one
  | { view: "inbox" }
  | { view: "plans" }
  | { view: "plan"; id: string }
  | ReviewRoute
  | { view: "knowledge"; path?: string; note?: string }
  | { view: "setup"; file: string; project?: string } // an agents file's agents set up (D.23);

// a skill just imported to the library: a new one, or one whose files it replaced
export type Imported = "new" | "replaced";

export function parse(hash: string): Route {
  const [path = "", query = ""] = hash.replace(/^#\/?/, "").split("?");
  const [first = "", second, third] = path.split("/");
  const id = second ? decodeURIComponent(second) : "";
  const params = new URLSearchParams(query);
  if (first === "sessions" && id) return { view: "session", key: id };
  if (first === "projects" && !id) return { view: "projects" };
  if (first === "library" && id === "tools" && third && third !== "more") {
    return params.get("connect") ? { view: "tool", name: decodeURIComponent(third), connect: true } : { view: "tool", name: decodeURIComponent(third) };
  }
  if (first === "library") {
    const shelf = LIBRARY_SHELVES.find((s) => s.id === id)?.id ?? "apps";
    if (third !== "more") return { view: "library", shelf };
    const install = params.get("install");
    const project = params.get("project");
    return { view: "library", shelf, more: true, ...(install ? { install } : {}), ...(project ? { project } : {}) };
  }
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
  if (first === "tools") return { view: "addons" };
  if (first === "discover") {
    const [, , kind, name] = path.split("/");
    if (id && (kind === "apps" || kind === "agents" || kind === "addons") && name) return { view: "discover-item", source: id, kind, name: decodeURIComponent(name) };
  }
  if (first === "settings") {
    const section = SETTINGS_SECTIONS.find((s) => s.id === id)?.id ?? "models";
    const helper = section === "helpers" ? third : undefined;
    return helper ? { view: "settings", section, helper: decodeURIComponent(helper) } : { view: "settings", section };
  }
  if (first === "projects" && id === "new") {
    const folder = params.get("folder");
    return folder ? { view: "edit-project", folder } : { view: "edit-project" };
  }
  if (first === "projects" && id && PROJECT_TABS.includes(third as ProjectTab)) return { view: "project", id, tab: third as ProjectTab };
  if (first === "projects" && id && third === "agents") {
    const agent = path.split("/")[3];
    if (agent && agent !== "new") return { view: "edit-agent", project: id, id: decodeURIComponent(agent) };
    const from = params.get("from");
    const plan = parse(params.get("plan") ?? "");
    if (plan.view === "review-plan") return { view: "edit-agent", project: id, plan };
    if (from && params.get("job")) return { view: "edit-agent", project: id, from, job: true };
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
  if (first === "plans" && id === "review") {
    const session = params.get("session");
    const agent = params.get("agent");
    const runner = params.get("runner");
    const draft = params.get("draft");
    const path = params.get("path");
    return {
      view: "review-plan",
      ...(draft ? { draft } : {}),
      ...(path || !draft ? { path: path ?? "" } : {}),
      ...(session ? { session } : {}),
      ...(agent ? { agent } : {}),
      ...(runner ? { runner } : {}),
    };
  }
  if (first === "plans" && id) return { view: "plan", id };
  if (first === "plans") return { view: "plans" };
  if (first === "chat" && id === "ask") return { view: "ask" };
  if (first === "chat") {
    const agent = params.get("agent");
    const say = params.get("say");
    return { view: "chat", ...(agent ? { agent } : {}), ...(say ? { say } : {}), ...(params.get("new") ? { new: true } : {}) };
  }
  if (first === "setup" && id) {
    const project = params.get("project");
    return { view: "setup", file: id, ...(project ? { project } : {}) };
  }
  if (first === "notes") {
    const path = params.get("path");
    const note = params.get("note");
    return { view: "knowledge", ...(path ? { path } : {}), ...(note ? { note } : {}) };
  }
  return { view: "projects" };
}

const KEPT = "handler.lastPage"; // the last page visited: where Handler opens again

/** Where Handler opens for this address: the page asked for, or for `#/` (nothing asked) the last
 *  one visited, else Projects. */
export function opening(hash: string, kept: string | null): string {
  if (hash && hash !== "#" && hash !== "#/") return hash;
  return kept?.startsWith("#/") && kept !== "#/" ? kept : "#/projects";
}

export const router = $state({ route: parse(typeof window === "undefined" ? "" : window.location.hash) });

// a page with unsaved changes (the skill editor) says so here: leaving it asks first
export const leaving = { unsaved: false };
let shown = typeof window === "undefined" ? "" : window.location.hash;

/** Kept: a page's address only (`#/…`), nothing else a link may carry. */
function keep(hash: string): void {
  if (!hash.startsWith("#/")) return;
  try {
    localStorage.setItem(KEPT, hash);
  } catch {
    /* storage unavailable: Handler opens on Projects */
  }
}

export function startRouter(): void {
  let kept: string | null = null;
  try {
    kept = localStorage.getItem(KEPT);
  } catch {
    /* as above */
  }
  const start = opening(window.location.hash, kept);
  if (start !== window.location.hash) {
    history.replaceState(null, "", start);
    shown = start;
    router.route = parse(start);
  }
  keep(start);
  window.addEventListener("hashchange", () => {
    if (leaving.unsaved && !confirm("Leave without saving your changes?")) {
      history.replaceState(null, "", shown || "#/projects");
      return;
    }
    leaving.unsaved = false;
    shown = window.location.hash;
    router.route = parse(shown);
    keep(shown);
  });
}

export function href(route: Route): string {
  switch (route.view) {
    case "projects":
      return "#/projects";
    case "library": {
      if (!route.more) return route.shelf === "apps" ? "#/library" : `#/library/${route.shelf}`;
      const query = new URLSearchParams({ ...(route.install ? { install: route.install } : {}), ...(route.project ? { project: route.project } : {}) }).toString();
      return `#/library/${route.shelf}/more${query ? `?${query}` : ""}`;
    }
    case "tool":
      return `#/library/tools/${encodeURIComponent(route.name)}${route.connect ? "?connect=1" : ""}`;
    case "project":
      if (route.tab) return `#/projects/${encodeURIComponent(route.id)}/${route.tab}`;
      return `#/projects/${encodeURIComponent(route.id)}${route.agent ? `?agent=${encodeURIComponent(route.agent)}` : ""}`;
    case "edit-project":
      return route.folder ? `#/projects/new?folder=${encodeURIComponent(route.folder)}` : "#/projects/new";
    case "edit-agent":
      if (route.id) return `#/projects/${encodeURIComponent(route.project)}/agents/${encodeURIComponent(route.id)}`;
      if (route.plan) return `#/projects/${encodeURIComponent(route.project)}/agents/new?plan=${encodeURIComponent(href(route.plan))}`;
      return `#/projects/${encodeURIComponent(route.project)}/agents/new${route.from ? `?from=${encodeURIComponent(route.from)}${route.job ? "&job=1" : ""}` : ""}`;
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
      return `#/settings/${route.section}${route.helper ? `/${encodeURIComponent(route.helper)}` : ""}`;
    case "skills":
      return "#/skills";
    case "addons":
      return "#/tools";
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
    case "plans":
      return "#/plans";
    case "plan":
      return `#/plans/${encodeURIComponent(route.id)}`;
    case "review-plan": {
      const params = new URLSearchParams();
      if (route.session) params.set("session", route.session);
      if (route.draft) params.set("draft", route.draft);
      if (route.agent) params.set("agent", route.agent);
      if (route.path !== undefined) params.set("path", route.path);
      if (route.runner) params.set("runner", route.runner);
      return `#/plans/review?${params}`;
    }
    case "ask":
      return "#/chat/ask";
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
      return query ? `#/notes?${query}` : "#/notes";
    }
    case "setup":
      return `#/setup/${encodeURIComponent(route.file)}${route.project ? `?project=${encodeURIComponent(route.project)}` : ""}`;
  }
}

/** Go to `route`; `replace` keeps the current entry out of the history (for action routes). */
export function navigate(route: Route, replace = false): void {
  if (replace) {
    shown = href(route);
    history.replaceState(null, "", shown);
    router.route = route;
    keep(shown);
  } else {
    window.location.hash = href(route);
  }
}
