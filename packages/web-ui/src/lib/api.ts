// Control API client (contract D). Types come from the generated contracts (schemas/).
import { token } from "./auth";
import type {
  SpeechRequest,
  DraftPreview,
  Transcription,
  Voice,
  VoiceSettings,
  AccountInfo,
  AgentChecks,
  Check,
  CheckRun,
  Improvement,
  UseRef,
  Uses,
  NetworkFilterInfo,
  SecretInfo,
  AreaInfo,
  AreaRequest,
  SessionChanges,
  SessionFile,
  SessionFolder,
  SessionFound,
  SessionMounts,
  AccountLoginRequest,
  AccountRequest,
  AddonInfo,
  AddonInstalled,
  AddonPreview,
  AgentRequest,
  App,
  ActionRun,
  AskTurn,
  AssistantAnswer,
  Automation,
  AutomationCheck,
  AutomationExample,
  AutomationRun,
  AutomationView,
  AppLink,
  AppLog,
  InboxMessage,
  BindingInfo,
  BindingRequest,
  CreateSkillRequest,
  SkillFile,
  SkillFileRequest,
  SkillInfo,
  SkillRequest,
  KnowledgeFolderView,
  KnowledgeListing,
  KnowledgeNote,
  LoginWindow,
  Build,
  BuildLog,
  CreateDirectoryRequest,
  CreateProjectRequest,
  Agent,
  HandlerNeed,
  AgentsFile,
  ExportAgentsRequest,
  AgentsExport,
  SessionInput,
  DirectoryListing,
  EgressEvent,
  HarnessInfo,
  Health,
  Problem,
  ProviderInfo,
  ProviderRequest,
  ProviderTemplate,
  Project,
  ProjectSettingsRequest,
  RemotePairing,
  RemoteStatus,
  Session,
  ImageUpdates,
  RuntimeCheck,
  ToolboxContainerfile,
  ToolboxInfo,
  WorkFoldersInfo,
  CacheDeclaration,
  CachesInfo,
  CacheSizes,
  ModelAccess,
  Source,
  SourceItemDetail,
} from "./contracts.gen";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly title: string,
    readonly detail?: string | null,
  ) {
    super(detail ? `${title}: ${detail}` : title);
  }
}

async function call<T>(method: string, path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
  const json = body === undefined ? undefined : JSON.stringify(body);
  const response = await send(method, path, json, { ...(json === undefined ? {} : { "Content-Type": "application/json" }), ...headers });
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

/** The request with the token; ApiError when it fails (problem details). */
async function send(method: string, path: string, body?: BodyInit, headers?: Record<string, string>): Promise<Response> {
  const response = await fetch(path, { method, headers: { Authorization: `Bearer ${token() ?? ""}`, ...headers }, body });
  if (!response.ok) {
    let problem: Partial<Problem> = {};
    try {
      problem = (await response.json()) as Problem;
    } catch {
      /* not a problem+json body */
    }
    throw new ApiError(response.status, problem.title ?? response.statusText, problem.detail);
  }
  return response;
}

/** API path of a file of a skill (each part encoded). */
function automationPath(name: string): string {
  return `/v1/automations/${encodeURIComponent(name)}`;
}

function skillFilePath(name: string, path: string): string {
  return `/v1/skills/${encodeURIComponent(name)}/files/${path.split("/").map(encodeURIComponent).join("/")}`;
}

/** API path of an image target: a harness name, or "addon:<name>" (G.4). */
export function imagePath(target: string): string {
  if (target === "toolbox" || target === "network-filter") return `/v1/${target}`; // handler's own and the shared base
  return target.startsWith("addon:")
    ? `/v1/addons/${encodeURIComponent(target.slice("addon:".length))}`
    : `/v1/harnesses/${encodeURIComponent(target)}`;
}

export const api = {
  health: () => call<Health>("GET", "/v1/health"),
  harnesses: () => call<HarnessInfo[]>("GET", "/v1/harnesses"),
  toolbox: () => call<ToolboxInfo>("GET", "/v1/toolbox"),
  networkFilter: () => call<NetworkFilterInfo>("GET", "/v1/network-filter"), // the egress proxy's image (D.4)
  runtime: () => call<RuntimeCheck>("GET", "/v1/runtime"), // can this host run sandboxes (A.8)
  // automatic image updates (D.4): the network filter, every built harness and addon image, not the toolbox
  imageUpdates: () => call<ImageUpdates>("GET", "/v1/image-updates"),
  setImageUpdates: (schedule: ImageUpdates["schedule"]) => call<ImageUpdates>("PUT", "/v1/image-updates", { schedule }),
  runImageUpdates: () => call<ImageUpdates>("POST", "/v1/image-updates/run"),
  // the user's toolbox Containerfile (B.6): saved here, built by the next toolbox rebuild
  toolboxContainerfile: () => call<ToolboxContainerfile>("GET", "/v1/toolbox/containerfile"),
  saveToolboxContainerfile: (content: string) =>
    call<ToolboxContainerfile>("PUT", "/v1/toolbox/containerfile", { content }),
  addons: () => call<AddonInfo[]>("GET", "/v1/addons"),
  // installing addons (G.5): from a source (source:<source>/<name>), a folder or an archive;
  // preview first
  previewAddon: (source: string) => call<AddonPreview>("POST", "/v1/addons/preview", { source }),
  installAddon: (source: string, digest: string) =>
    call<AddonInstalled>("POST", "/v1/addons/install", { source, digest }),
  removeAddon: (name: string) => call<void>("DELETE", `/v1/addons/${encodeURIComponent(name)}`),
  // bindings (G.2, D.15): written from the form (secret values go to the secret store), or by hand
  bindings: () => call<BindingInfo[]>("GET", "/v1/bindings"),
  createBinding: (body: BindingRequest) => call<BindingInfo>("POST", "/v1/bindings", body),
  updateBinding: (name: string, body: BindingRequest) => call<BindingInfo>("PUT", `/v1/bindings/${encodeURIComponent(name)}`, body),
  deleteBinding: (name: string) => call<void>("DELETE", `/v1/bindings/${encodeURIComponent(name)}`),
  // skills (D.17): the library, offered to every agent; projects give some to all their agents
  skills: () => call<SkillInfo[]>("GET", "/v1/skills"),
  skill: (name: string) => call<SkillInfo>("GET", `/v1/skills/${encodeURIComponent(name)}`),
  createSkill: (body: CreateSkillRequest) => call<SkillInfo>("POST", "/v1/skills", body),
  updateSkill: (name: string, body: SkillRequest) => call<SkillInfo>("PUT", `/v1/skills/${encodeURIComponent(name)}`, body),
  deleteSkill: (name: string) => call<void>("DELETE", `/v1/skills/${encodeURIComponent(name)}`),
  skillFile: (name: string, path: string) => call<SkillFile>("GET", skillFilePath(name, path)),
  writeSkillFile: (name: string, path: string, body: SkillFileRequest) => call<SkillInfo>("PUT", skillFilePath(name, path), body),
  deleteSkillFile: (name: string, path: string) => call<SkillInfo>("DELETE", skillFilePath(name, path)),
  exportSkill: async (name: string) => (await send("GET", `/v1/skills/${encodeURIComponent(name)}/archive`)).blob(),
  importSkill: async (archive: Blob, options: { project?: string | null; replace?: boolean }) => {
    const query = new URLSearchParams();
    if (options.project) query.set("project", options.project);
    if (options.replace) query.set("replace", "true");
    const response = await send("POST", `/v1/skills/import?${query}`, archive, { "Content-Type": "application/zip" });
    return (await response.json()) as SkillInfo;
  },
  // a folderless agent's session's folder as a skill (D.18)
  importSkillSession: (sessionId: string, options: { project?: string | null; replace?: boolean }) => {
    const query = new URLSearchParams();
    if (options.project) query.set("project", options.project);
    if (options.replace) query.set("replace", "true");
    return call<SkillInfo>("POST", `/v1/skills/import-session/${encodeURIComponent(sessionId)}?${query}`);
  },
  // an agent's checks (D.20): runs of a job kept with their right answer, run when asked
  agentChecks: (agentId: string) => call<AgentChecks>("GET", `/v1/agents/${agentId}/checks`),
  keepCheck: (agentId: string, fromRun: string, name: string, compare: string[]) =>
    call<Check>("POST", `/v1/agents/${agentId}/checks`, { fromRun, name, compare }),
  updateCheck: (agentId: string, checkId: string, name: string, compare: string[]) =>
    call<Check>("PUT", `/v1/agents/${agentId}/checks/${checkId}`, { name, compare }),
  deleteCheck: (agentId: string, checkId: string) => call<void>("DELETE", `/v1/agents/${agentId}/checks/${checkId}`),
  runChecks: (agentId: string) => call<CheckRun>("POST", `/v1/agents/${agentId}/checks/run`),
  // its improvements (D.21): its instructions rewritten until its checks pass, an attempt kept
  improvements: (agentId: string) => call<Improvement[]>("GET", `/v1/agents/${agentId}/improvements`),
  improve: (agentId: string, goal: string, maxAttempts: number, maxMinutes: number) =>
    call<Improvement>("POST", `/v1/agents/${agentId}/improvements`, { goal, maxAttempts, maxMinutes }),
  stopImprovement: (agentId: string, id: string) => call<Improvement>("POST", `/v1/agents/${agentId}/improvements/${id}/stop`),
  keepAttempt: (agentId: string, id: string, attempt: number) =>
    call<Improvement>("POST", `/v1/agents/${agentId}/improvements/${id}/keep`, { attempt }),
  // what a thing uses and what uses it (D.22)
  uses: (kind: UseRef["kind"], id: string) => call<Uses>("GET", `/v1/uses/${kind}/${id.split("/").map(encodeURIComponent).join("/")}`),
  // Handler's needs (D.18): its features that need an agent (the helpers), each with the
  // definition an agent is set up from for it, then given
  handlerNeeds: () => call<HandlerNeed[]>("GET", "/v1/handler-needs"),
  // the agent handler's feature uses (one that fits): set up for it, or one of yours
  giveHandlerNeedAgent: (name: string, agentId: string) =>
    call<HandlerNeed>("PUT", `/v1/handler-needs/${encodeURIComponent(name)}`, { agentId }),
  // an agents file being imported (D.23); set it up = create its agents with its origin
  agentsFile: (name: string) => call<AgentsFile>("GET", `/v1/agents-files/${encodeURIComponent(name)}`),
  forgetAgentsFile: (name: string) => call<void>("DELETE", `/v1/agents-files/${encodeURIComponent(name)}`),
  // a project's agents as one file: what it would hold, then the file
  exportAgentsDraft: (body: ExportAgentsRequest) => call<AgentsExport>("POST", "/v1/agents-files/export", { ...body, dryRun: true }),
  exportAgents: async (body: ExportAgentsRequest): Promise<{ file: Blob; filename: string }> => {
    const response = await send("POST", "/v1/agents-files/export", JSON.stringify(body), { "Content-Type": "application/json" });
    const filename = /filename="([^"]+)"/.exec(response.headers.get("content-disposition") ?? "")?.[1] ?? `${body.name}-agents.zip`;
    return { file: await response.blob(), filename };
  },
  // an agents file read, for its agents to be set up (#/setup/:file)
  importAgents: async (file: Blob) =>
    (await (await send("POST", "/v1/agents-files/import", file, { "Content-Type": "application/zip" })).json()) as AgentsFile,
  importSkillUrl: (url: string, options: { replace?: boolean }) =>
    call<SkillInfo>("POST", `/v1/skills/import-url${options.replace ? "?replace=true" : ""}`, { url }),
  knowledge: () => call<KnowledgeListing>("GET", "/v1/knowledge"),
  // D.5: the root (null: back to the default), folders, and reading what they hold
  setKnowledgeRoot: (root: string | null, create = false) =>
    call<KnowledgeListing>("PUT", "/v1/knowledge/root", { root, create }),
  createKnowledgeFolder: (path: string) => call<KnowledgeListing>("POST", "/v1/knowledge/folders", { path }),
  browseKnowledge: (path: string) =>
    call<KnowledgeFolderView>("GET", `/v1/knowledge/browse?path=${encodeURIComponent(path)}`),
  knowledgeNote: (path: string) => call<KnowledgeNote>("GET", `/v1/knowledge/note?path=${encodeURIComponent(path)}`),
  // image rebuilds (D.4, G.4): the daemon builds from the files on disk; clients only name the target
  rebuild: (target: string) =>
    call<Build>("POST", `${imagePath(target)}/rebuild`),
  builds: () => call<Build[]>("GET", "/v1/builds"),
  build: (id: string) => call<Build>("GET", `/v1/builds/${id}`),
  buildLog: (id: string, offset: number) => call<BuildLog>("GET", `/v1/builds/${id}/log?offset=${offset}`),
  cancelBuild: (id: string) => call<Build>("POST", `/v1/builds/${id}/cancel`),
  // the folder picker, inside the work folders (D.13)
  directories: (path?: string) => call<DirectoryListing>("GET", `/v1/directories${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  createDirectory: (body: CreateDirectoryRequest) => call<DirectoryListing>("POST", "/v1/directories", body),
  // accounts (D.9): a harness and a description; handler keeps the login
  accounts: () => call<AccountInfo[]>("GET", "/v1/accounts"),
  createAccount: (body: AccountRequest) => call<AccountInfo>("POST", "/v1/accounts", body),
  updateAccount: (name: string, body: AccountRequest) => call<AccountInfo>("PUT", `/v1/accounts/${encodeURIComponent(name)}`, body),
  deleteAccount: (name: string) => call<void>("DELETE", `/v1/accounts/${encodeURIComponent(name)}`),
  setAccountLogin: (name: string, body: AccountLoginRequest) =>
    call<AccountInfo>("PUT", `/v1/accounts/${encodeURIComponent(name)}/login`, body),
  forgetAccountLogin: (name: string) => call<AccountInfo>("DELETE", `/v1/accounts/${encodeURIComponent(name)}/login`),
  openLoginWindow: (name: string) => call<LoginWindow>("POST", `/v1/accounts/${encodeURIComponent(name)}/login/window`),
  // providers (D.12): written from the form (the key goes to the secret store), or by hand
  providers: () => call<ProviderInfo[]>("GET", "/v1/providers"),
  providerTemplates: () => call<ProviderTemplate[]>("GET", "/v1/provider-templates"),
  createProvider: (body: ProviderRequest) => call<ProviderInfo>("POST", "/v1/providers", body),
  updateProvider: (name: string, body: ProviderRequest) => call<ProviderInfo>("PUT", `/v1/providers/${encodeURIComponent(name)}`, body),
  deleteProvider: (name: string) => call<void>("DELETE", `/v1/providers/${encodeURIComponent(name)}`),
  // areas (D.19): Work, Personal, a client, with their colours
  areas: () => call<AreaInfo[]>("GET", "/v1/areas"),
  createArea: (body: AreaRequest) => call<AreaInfo>("POST", "/v1/areas", body),
  updateArea: (body: AreaRequest) => call<AreaInfo>("PUT", `/v1/areas/${encodeURIComponent(body.name)}`, body),
  deleteArea: (name: string) => call<void>("DELETE", `/v1/areas/${encodeURIComponent(name)}`),
  // the work folders (D.13): where agents may work, owned by this computer
  folders: () => call<WorkFoldersInfo>("GET", "/v1/folders"),
  setFolders: (roots: string[]) => call<WorkFoldersInfo>("PUT", "/v1/folders", { roots }),
  // the toolbox's caches (D.8): kept between sessions, each project's own or the global ones
  caches: () => call<CachesInfo>("GET", "/v1/caches"),
  setCaches: (caches: Record<string, CacheDeclaration>) => call<CachesInfo>("PUT", "/v1/caches", { caches }),
  cacheSizes: () => call<CacheSizes>("GET", "/v1/caches/sizes"), // measured: may take seconds
  emptyGlobalCaches: () => call<void>("DELETE", "/v1/caches/files"),
  emptyCache: (name: string) => call<void>("DELETE", `/v1/caches/${encodeURIComponent(name)}/files`),
  emptyProjectCaches: (projectId: string) => call<void>("DELETE", `/v1/projects/${encodeURIComponent(projectId)}/caches`),
  emptyProjectCache: (projectId: string, name: string) =>
    call<void>("DELETE", `/v1/projects/${encodeURIComponent(projectId)}/caches/${encodeURIComponent(name)}/files`),

  // secrets (D.14, E3): every one handler uses, how agents get it; values written, never read back
  secrets: () => call<SecretInfo[]>("GET", "/v1/secrets"),
  deleteSecret: (path: string) => call<void>("DELETE", `/v1/secrets/${path.split("/").map(encodeURIComponent).join("/")}`),

  // apps (H): deploy and rollback answer once done (a deploy runs the app's tests)
  apps: () => call<App[]>("GET", "/v1/apps"),
  app: (name: string) => call<App>("GET", `/v1/apps/${encodeURIComponent(name)}`),
  /** An app file (an export, H.15): a new app (`added`), or the next version of one you have. */
  addApp: async (file: Blob): Promise<{ app: App; added: boolean }> => {
    const response = await send("POST", "/v1/apps", file, { "Content-Type": "application/zip" });
    return { app: (await response.json()) as App, added: response.status === 201 };
  },
  /** Its code as one file (H.15), and the name to save it as. */
  exportApp: async (name: string): Promise<{ file: Blob; filename: string }> => {
    const response = await send("GET", `/v1/apps/${encodeURIComponent(name)}/export`);
    const filename = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? `${name}.zip`;
    return { file: await response.blob(), filename };
  },
  // sources (D.26): git repositories offering apps, agents and addons; the official one first
  sources: () => call<Source[]>("GET", "/v1/sources"),
  addSource: (url: string) => call<Source>("POST", "/v1/sources", { url }),
  refreshSource: (id: string) => call<Source>("POST", `/v1/sources/${encodeURIComponent(id)}/refresh`),
  removeSource: (id: string) => call<void>("DELETE", `/v1/sources/${encodeURIComponent(id)}`),
  /** An item's page (D.26): its README and what its manifest says, before it is installed. */
  sourceItem: (source: string, kind: "apps" | "agents" | "addons", name: string) =>
    call<SourceItemDetail>("GET", `/v1/sources/${encodeURIComponent(source)}/${kind}/${encodeURIComponent(name)}`),
  /** An app a source offers, its code taken: a new app, or the next version of one you have. */
  appFromSource: async (source: string, name: string): Promise<{ app: App; added: boolean }> => {
    const response = await send("POST", `/v1/sources/${encodeURIComponent(source)}/apps/${encodeURIComponent(name)}`);
    return { app: (await response.json()) as App, added: response.status === 201 };
  },
  /** Agents a source offers, read as an agents file is: their set-up page next, by its name. */
  agentsFromSource: (source: string, name: string) =>
    call<AgentsFile>("POST", `/v1/sources/${encodeURIComponent(source)}/agents/${encodeURIComponent(name)}`),
  // an app's action, what you ask it (H.12): done now, or its agent's run read again until it ends
  act: (name: string, action: string, fields: Record<string, unknown>) =>
    call<ActionRun>("POST", `/v1/apps/${encodeURIComponent(name)}/actions/${encodeURIComponent(action)}`, { fields }),
  setAppAskable: (name: string, askable: boolean) => call<App>("PUT", `/v1/apps/${encodeURIComponent(name)}/askable`, { askable }),
  // Ask (D.24): the exchange so far, the person's words last
  ask: (turns: AskTurn[], timezone: string) => call<AssistantAnswer>("POST", "/v1/ask", { turns, timezone }),
  // Voice (D.25): what writes down what you say, and a recording written down (never kept)
  voice: () => call<Voice>("GET", "/v1/voice"),
  setVoice: (settings: VoiceSettings) => call<Voice>("PUT", "/v1/voice", settings),
  transcribe: (speech: SpeechRequest) => call<Transcription>("POST", "/v1/voice/transcribe", speech),
  actionRun: (name: string, action: string, runId: string) =>
    call<ActionRun>("GET", `/v1/apps/${encodeURIComponent(name)}/actions/${encodeURIComponent(action)}/runs/${encodeURIComponent(runId)}`),
  deployApp: (name: string) => call<App>("POST", `/v1/apps/${encodeURIComponent(name)}/deploy`),
  rollbackApp: (name: string) => call<App>("POST", `/v1/apps/${encodeURIComponent(name)}/rollback`),
  stopApp: (name: string) => call<App>("POST", `/v1/apps/${encodeURIComponent(name)}/stop`),
  uninstallApp: (name: string) => call<void>("DELETE", `/v1/apps/${encodeURIComponent(name)}`),
  setAppSecret: (name: string, secret: string, value: string) =>
    call<App>("PUT", `/v1/apps/${encodeURIComponent(name)}/secrets/${encodeURIComponent(secret)}`, { value }),
  unsetAppSecret: (name: string, secret: string) =>
    call<App>("DELETE", `/v1/apps/${encodeURIComponent(name)}/secrets/${encodeURIComponent(secret)}`),
  // what the person gives an app's needs (H.2): a folder, an agent that fits
  setAppFile: (name: string, need: string, path: string) =>
    call<App>("PUT", `/v1/apps/${encodeURIComponent(name)}/files/${encodeURIComponent(need)}`, { path }),
  setAppAgent: (name: string, need: string, agentId: string) =>
    call<App>("PUT", `/v1/apps/${encodeURIComponent(name)}/agents/${encodeURIComponent(need)}`, { agentId }),
  setAppPersons: (name: string, persons: string[]) =>
    call<App>("PUT", `/v1/apps/${encodeURIComponent(name)}/persons`, { persons }),
  inbox: () => call<InboxMessage[]>("GET", "/v1/inbox"),
  markRead: (id: string) => call<InboxMessage>("POST", `/v1/inbox/${encodeURIComponent(id)}/read`),
  openApp: (name: string) => call<AppLink>("POST", `/v1/apps/${encodeURIComponent(name)}/open`),
  appLog: (name: string) => call<AppLog>("GET", `/v1/apps/${encodeURIComponent(name)}/log`),

  automations: () => call<AutomationView[]>("GET", "/v1/automations"),
  automation: (name: string) => call<AutomationView>("GET", automationPath(name)),
  automationExamples: () => call<AutomationExample[]>("GET", "/v1/automation-examples"),
  // an agent run's agent by id (`agentId`): its names written in the file, bound (I.1)
  createAutomation: (name: string, source: { from: string } | { definition: Automation; agentId: string | null; enable: boolean }) =>
    call<AutomationView>("POST", "/v1/automations", { name, ...source }),
  deleteAutomation: (name: string) => call<void>("DELETE", automationPath(name)),
  updateAutomation: (name: string, definition: Automation, agentId: string | null) =>
    call<AutomationView>("PUT", automationPath(name), { definition, agentId }),
  checkAutomation: (definition: Automation, agentId: string | null) =>
    call<AutomationCheck>("POST", "/v1/automations/check", { definition, agentId }),
  automationFile: async (name: string, path: string) =>
    (await send("GET", `${automationPath(name)}/files/${path.split("/").map(encodeURIComponent).join("/")}`)).text(),
  enableAutomation: (name: string) => call<AutomationView>("POST", `${automationPath(name)}/enable`),
  disableAutomation: (name: string) => call<AutomationView>("POST", `${automationPath(name)}/disable`),
  tryAutomation: (name: string, sessionId?: string) => call<AutomationRun>("POST", `${automationPath(name)}/try`, sessionId ? { sessionId } : {}),
  automationRuns: (name: string) => call<AutomationRun[]>("GET", `${automationPath(name)}/runs`),
  automationRunLog: async (name: string, id: string) =>
    (await send("GET", `${automationPath(name)}/runs/${encodeURIComponent(id)}/log`)).text(),
  cancelAutomationRun: (name: string, id: string) =>
    call<AutomationRun>("POST", `${automationPath(name)}/runs/${encodeURIComponent(id)}/cancel`),
  sessionAutomationRuns: (sessionId: string) =>
    call<AutomationRun[]>("GET", `/v1/sessions/${encodeURIComponent(sessionId)}/automation-runs`),
  // its folder (F.8): what changed since it started, a folder, a file; paths relative to it
  sessionChanges: (sessionId: string) => call<SessionChanges>("GET", `/v1/sessions/${encodeURIComponent(sessionId)}/changes`),
  // what else its sandbox sees; `mount`: one of them to read (its target), default its folder
  sessionMounts: (sessionId: string) => call<SessionMounts>("GET", `/v1/sessions/${encodeURIComponent(sessionId)}/mounts`),
  sessionFolder: (sessionId: string, path: string, mount?: string) =>
    call<SessionFolder>("GET", `/v1/sessions/${encodeURIComponent(sessionId)}/folder?${new URLSearchParams({ path, ...(mount ? { mount } : {}) })}`),
  revealSessionPath: (sessionId: string, path: string, mount?: string) =>
    call<void>("POST", `/v1/sessions/${encodeURIComponent(sessionId)}/reveal`, { path, ...(mount ? { mount } : {}) }),
  sessionFind: (sessionId: string, q: string) =>
    call<SessionFound>("GET", `/v1/sessions/${encodeURIComponent(sessionId)}/find?${new URLSearchParams({ q })}`),
  sessionFile: (sessionId: string, path: string, mount?: string) =>
    call<SessionFile>("GET", `/v1/sessions/${encodeURIComponent(sessionId)}/file?${new URLSearchParams({ path, ...(mount ? { mount } : {}) })}`),

  // projects and their agents
  projects: () => call<Project[]>("GET", "/v1/projects"),
  project: (id: string) => call<Project>("GET", `/v1/projects/${id}`),
  createProject: (body: CreateProjectRequest) => call<Project>("POST", "/v1/projects", body),
  updateProject: (id: string, body: ProjectSettingsRequest) => call<Project>("PUT", `/v1/projects/${id}`, body),
  pinProject: (id: string, pinned: boolean) => call<Project>("PUT", `/v1/projects/${id}/pinned`, { pinned }),
  deleteProject: (id: string) => call<void>("DELETE", `/v1/projects/${id}`),

  // every agent, whatever its home (D.1): a project, an app or Chat, none (Other folders)
  agents: () => call<Agent[]>("GET", "/v1/agents"),
  agent: (id: string) => call<Agent>("GET", `/v1/agents/${id}`),
  createAgent: (body: AgentRequest) => call<Agent>("POST", "/v1/agents", body),
  updateAgent: (id: string, body: AgentRequest) => call<Agent>("PUT", `/v1/agents/${id}`, body),
  deleteAgent: (id: string) => call<void>("DELETE", `/v1/agents/${id}`),
  setEgress: (id: string, egress: "enforce" | "log-only") =>
    call<Agent>("PATCH", `/v1/agents/${id}`, { egress }),
  egressEvents: (id: string) => call<EgressEvent[]>("GET", `/v1/agents/${id}/egress-events`),

  sessions: () => call<Session[]>("GET", "/v1/sessions"),
  agentSessions: (agentId: string) => call<Session[]>("GET", `/v1/sessions?agentId=${encodeURIComponent(agentId)}`),
  // the runs on a skill (D.18)
  skillRuns: (name: string) => call<Session[]>("GET", `/v1/sessions?subject=${encodeURIComponent(`skill:${name}`)}`),
  // a run of an agent with an interface (D.18); `fromSkill`: a folderless agent's session starting as that skill
  startRun: (agentId: string, input: SessionInput, model?: ModelAccess) =>
    call<Session>("POST", "/v1/sessions", { agentId, input, model, origin: "ui" }),
  createSessionFromSkill: (agentId: string, fromSkill: string, model?: ModelAccess) =>
    call<Session>("POST", "/v1/sessions", { agentId, fromSkill, model, origin: "ui" }),
  session: (id: string) => call<Session>("GET", `/v1/sessions/${id}`),
  // `prompt`: the request the daemon sends first (after the agent's instructions); `model`: one
  // of the agent's (default: its first, D.1)
  createSession: (agentId: string, acpSessionId?: string, prompt?: string, model?: ModelAccess) =>
    call<Session>("POST", "/v1/sessions", { agentId, acpSessionId, prompt, model, origin: "ui" }),
  stopSession: (id: string) => call<Session>("POST", `/v1/sessions/${id}/stop`),
  // its turn cancelled; a run waiting for its turn does not start (D.18)
  cancelSession: (id: string) => call<Session>("POST", `/v1/sessions/${id}/cancel`),
  deleteSession: (id: string) => call<void>("DELETE", `/v1/sessions/${id}`),
  /** A session working on a draft of an app's code (H.15): a copy of `app`'s, or empty for a new app. */
  // a draft opened (H.16): its code at its own address, on copies, until used or thrown away
  openAppDraft: (sessionId: string) => call<DraftPreview>("POST", `/v1/apps/from-draft/${encodeURIComponent(sessionId)}/open`),
  createAppDraft: (agentId: string, app?: string) => call<Session>("POST", "/v1/sessions", { agentId, appDraft: app ? { app } : {} }),
  /** A session's draft used: the app's next version, or a new app (`added`). */
  useAppDraft: async (sessionId: string): Promise<{ app: App; added: boolean }> => {
    const response = await send("POST", `/v1/apps/from-draft/${encodeURIComponent(sessionId)}`);
    return { app: (await response.json()) as App, added: response.status === 201 };
  },
  shareSession: (id: string, enabled: boolean) => call<Session>("PUT", `/v1/sessions/${id}/remote`, { enabled }),
  remote: () => call<RemoteStatus>("GET", "/v1/remote"),
  setGateway: (gatewayUrl: string, hostToken: string) =>
    call<RemoteStatus>("PUT", "/v1/remote/gateway", { gatewayUrl, hostToken }),
  clearGateway: () => call<RemoteStatus>("DELETE", "/v1/remote/gateway"),
  // person "owner" (you) reaches sessions and apps; anyone else's device, apps only
  pairDevice: (name: string, person = "owner") =>
    call<RemotePairing>("POST", "/v1/remote/devices", { name, person, scope: person === "owner" ? "all" : "apps" }),
  revokeDevice: (id: string) => call<void>("DELETE", `/v1/remote/devices/${id}`),

};
