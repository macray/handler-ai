<script lang="ts">
  // Installing an app, on one page (H.2, the agents set-up page's layout): where it keeps its
  // data (a folder of yours, new or not; a project's folder lists the app from its side, H.14),
  // its other folders, its agents (set up from what the app brings, as its parts, or one of yours
  // that fits), its secrets, what you can ask it, what runs by itself (its suggestions, each off
  // until switched on), who opens it on a phone; beside them what it will be allowed to do.
  // Install does what is not done yet, in order, each through its own request (its folders, then
  // its agents), then deploys and ends on the app's page. Stopped midway, the page opened again
  // shows what is done and goes on.
  import Check from "@lucide/svelte/icons/check";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import FolderPicker from "../components/FolderPicker.svelte";
  import ModelAccessPicker from "../components/ModelAccessPicker.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import { fromSourceWords } from "../lib/sources";
  import { api, toolboxChanges, type ToolboxChanges } from "../lib/api";
  import ToolboxConfirm from "../components/ToolboxConfirm.svelte";
  import { agentChoice, dataNeed, reaches, suggested } from "../lib/apps";
  import { whenSentence } from "../lib/automations";
  import { chosenSpec, firstChoice, mayDo, missing, toolsAsked, type Choice } from "../lib/setup";
  import { freeName } from "../lib/text";
  import type { AddonInfo, Agent, App, AppAgentNeed, AutomationView, BindingInfo } from "../lib/contracts.gen";
  import { agentBody, projects } from "../lib/projects.svelte";
  import { remote } from "../lib/remote.svelte";
  import { href, navigate } from "../lib/router.svelte";

  let { name }: { name: string } = $props();

  let app = $state<App | null>(null);
  let agents = $state<Agent[]>([]);
  let automations = $state<AutomationView[]>([]);
  let bindings = $state<BindingInfo[]>([]);
  let addons = $state<AddonInfo[]>([]);
  let folders = $state<string[]>([]);
  let error = $state<string | null>(null);
  let doing = $state<string | null>(null); // the step under way

  // where its data goes: a folder of yours (made in the picker when new)
  let chosenFolder = $state("");
  let otherFolders = $state<Record<string, string>>({}); // its other folders needs → the folder chosen
  // its agents: set up from the app's definition, or one of yours that fits
  let modes = $state<Record<string, "setup" | "fit">>({});
  let choices = $state<Record<string, Choice>>({});
  let fitIds = $state<Record<string, string>>({});
  let secrets = $state<Record<string, string>>({});
  let switched = $state<Record<number, boolean>>({}); // suggestions turned on
  let persons = $state<string[] | null>(null);

  async function load(): Promise<void> {
    try {
      const [a, ag, au, bs, ad, k] = await Promise.all([
        api.app(name),
        api.agents(),
        api.automations().catch(() => []),
        api.bindings(),
        api.addons(),
        api.knowledge().catch(() => null),
      ]);
      [agents, automations, bindings, addons, folders] = [ag, au, bs, ad, k?.folders ?? []];
      for (const need of a.agents ?? []) {
        if (need.definition && !choices[need.name]) choices[need.name] = firstChoice(need.definition, bs, ad, folders);
        modes[need.name] ??= "setup";
      }
      persons ??= [...(a.persons ?? [])];
      app = a;
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    remote.start();
    void load();
  });

  const data = $derived(app ? dataNeed(app) : undefined);
  const others = $derived((app?.files ?? []).filter((f) => f.name !== data?.name));
  const toSetUp = $derived((app?.agents ?? []).filter((n) => !given(n)));
  const target = $derived(data?.path ?? chosenFolder);
  // the project whose folder it is: it lists the app (H.14), the app stays in Apps
  const project = $derived(target ? projects.list.find((p) => p.folder === target) : undefined);
  const devicesOf = $derived.by(() => {
    const out: Record<string, string[]> = { owner: [] };
    for (const d of remote.status?.devices ?? []) (out[d.person ?? "owner"] ??= []).push(d.name);
    return out;
  });

  function given(n: AppAgentNeed): boolean {
    return !!n.agentId && !n.problem;
  }

  /** Those of yours that fit, where its data is: an agent working in that folder. */
  function fitsOf(n: AppAgentNeed): Agent[] {
    return agents.filter((a) => (n.fits ?? []).includes(a.id) && (!n.worksIn || a.scope === target));
  }

  const todo = $derived.by(() => {
    if (!app) return [];
    const left: string[] = [];
    if (data && !data.path && !target) left.push(`the folder for ${data.name}`);
    for (const f of others) if (!f.path && !otherFolders[f.name]) left.push(`the folder for ${f.name}`);
    for (const n of toSetUp) {
      if (modes[n.name] === "fit") {
        if (!fitIds[n.name]) left.push(`the agent for ${n.name}`);
      } else if (n.definition) left.push(...missing(n.definition, choices[n.name]!, addons).map((m) => `${n.definition?.agentName}: ${m}`));
      else left.push(`${n.name}: ${n.problem ?? "its definition cannot be read"}`);
    }
    for (const s of app.secrets ?? []) if (!s.set && !secrets[s.name]?.trim()) left.push(`the secret ${s.name}`);
    return left;
  });

  /** What it will be allowed to do: what its version may reach, with the folders chosen; its
   *  agents set up; what runs by itself. */
  const allowed = $derived.by(() => {
    if (!app?.source.needs) return [];
    const files = (app.files ?? []).map((f) => ({ ...f, path: f.path ?? ((f.name === data?.name ? target : otherFolders[f.name]) || null) }));
    const lines = reaches(app.source.needs, { ...app, files }, (id) => agentChoice(agents.find((a) => a.id === id) ?? ({ id } as Agent), new Map()));
    for (const n of toSetUp)
      if (modes[n.name] === "setup" && n.definition) lines.push(`${n.definition.agentName}: ${mayDo(n.definition, n.worksIn ? target || "its folder" : null).join("; ")}.`);
    (app.suggests ?? []).forEach((s, i) => {
      if (switched[i]) lines.push(`Runs ${s.run.agent} ${whenSentence(suggested(app!, s).definition).toLowerCase()}, by itself.`);
    });
    return lines;
  });

  let toolbox = $state<ToolboxChanges | null>(null); // what setting up its agents adds to the toolbox
  let confirmedAdds: string[] = []; // confirmed, sent with its agents (B.6)

  async function step<T>(label: string, action: () => Promise<T>): Promise<T> {
    doing = label;
    return action();
  }

  async function install(): Promise<void> {
    if (!app) return;
    const a = app;
    error = null;
    const made: Record<string, string> = {}; // need → the agent set up for it
    try {
      // its folders first: its agents work in one of them
      if (data && !data.path) await step(`giving it ${target}`, () => api.setAppFile(a.name, data.name, target));
      for (const f of others) if (!f.path) await step(`giving it ${otherFolders[f.name]}`, () => api.setAppFile(a.name, f.name, otherFolders[f.name]!));
      // its agents: its parts (H.14), named apart from the agents already in their folder
      const setups = toSetUp.filter((n) => modes[n.name] === "setup" && n.definition);
      for (const n of setups) {
        const where = n.worksIn ? target : null;
        const taken = agents.filter((x) => !x.projectId && (x.scope ?? null) === where).map((x) => x.name ?? "");
        const named = freeName(n.definition!.agentName, taken, " ");
        const agent = await step(`setting up ${named}`, () =>
          api.createAgent({
            ...agentBody(chosenSpec(n.definition!, choices[n.name]!), { app: a.name, scope: where }, true, confirmedAdds),
            origin: n.origin,
            name: named,
          }),
        );
        made[n.name] = agent.id;
      }
      for (const n of toSetUp) {
        const id = made[n.name] ?? fitIds[n.name];
        if (id) await step(`giving it its agent ${n.name}`, () => api.setAppAgent(a.name, n.name, id));
      }
      for (const s of a.secrets ?? []) if (!s.set) await step(`keeping ${s.name}`, () => api.setAppSecret(a.name, s.name, secrets[s.name]!.trim()));
      const now = await step("reading what it was given", () => api.app(a.name));
      for (const [i, s] of (a.suggests ?? []).entries()) {
        const { name: auto, definition } = suggested(a, s);
        const agentId = now.agents?.find((n) => n.name === s.run.agent)?.agentId ?? null;
        if (switched[i] && !automations.some((x) => x.name === auto)) await step(`making ${auto}`, () => api.createAutomation(auto, { definition, agentId, enable: true }));
      }
      if (!a.current) await step("deploying: its tests, then its health check", () => api.deployApp(a.name));
      if (persons && persons.join() !== (a.persons ?? []).join()) await step("sharing it", () => api.setAppPersons(a.name, persons!));
      await projects.refresh();
      navigate({ view: "apps", app: a.name }, true);
    } catch (e) {
      toolbox = toolboxChanges(e);
      const failed = toolbox ? null : `While ${doing}: ${(e as Error).message}. What was done is kept: Install goes on from there.`;
      await load(); // what was done, shown; it clears the error: set after
      if (failed) error = failed;
    } finally {
      doing = null;
    }
  }

  async function cancel(): Promise<void> {
    if (app && !app.current && confirm(`Forget ${app.name}? It was never installed: its code and the agents set up for it here go; your folders stay.`)) {
      await api.uninstallApp(app.name).catch(() => {});
    }
    navigate({ view: "apps" }, true);
  }

  function togglePerson(person: string, on: boolean): void {
    const all = new Set(persons ?? []);
    if (on) all.add(person);
    else all.delete(person);
    persons = [...all].sort();
  }

  const showsWho = $derived(Object.keys(devicesOf).length > 1 || (remote.status?.devices ?? []).length > 0);
  // the steps shown, numbered in order
  const steps = $derived(
    [data && "where", app?.agents?.length && "agents", app?.secrets?.length && "secrets", app?.actions?.length && "actions", app?.suggests?.length && "suggests", showsWho && "who"].filter(Boolean),
  );
</script>

{#snippet head(step: string, heading: string, hint: string)}
  <div class="flex items-start gap-3">
    <span class="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">{steps.indexOf(step) + 1}</span>
    <div><h2 class="text-sm font-semibold">{heading}</h2>{#if hint}<p class="text-sm text-muted-foreground">{hint}</p>{/if}</div>
  </div>
{/snippet}

<PageHeader width="max-w-5xl" title="Install {name}" parent={{ label: "Apps", href: href({ view: "apps" }) }} />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-5xl space-y-6 px-8 py-10">
    <div class="space-y-1">
      {#if app}<p class="text-sm text-muted-foreground">{app.source.description ?? ""} <span class="fact">· {app.source.version ?? ""} · {fromSourceWords(app.fromSource, []) ?? "from a file"}</span></p>{/if}
    </div>
    {#if app?.source.error}
      <p class="text-sm text-danger">Its folder cannot be read: {app.source.error}</p>
    {:else if app}
      <div class="grid items-start gap-6 lg:grid-cols-[1fr_19rem]">
        <div class="space-y-4">
          {#if data}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="install-where">
              {@render head("where", "Where it keeps your files", `${data.description ?? data.name}: a folder of yours, new or one you have. The app and its agent share it.`)}
              <div class="space-y-2 pl-9 text-sm">
                {#if data.path}
                  <p data-testid="install-where-done"><Check class="mr-1 inline size-4 text-ok" /><span class="fact">{data.path}</span></p>
                {:else}
                  <FolderPicker bind:value={chosenFolder} used={Object.fromEntries(projects.list.map((p) => [p.folder, p.name]))} />
                {/if}
                {#if project}
                  <p class="text-xs text-muted-foreground" data-testid="install-where-project">The folder of the project {project.name}: its page will list {name} as using it. The app stays in Apps.</p>
                {/if}
                {#each others as f (f.name)}
                  <div class="space-y-1 pt-2">
                    <p>{f.description ?? f.name} <span class="text-muted-foreground">· {f.mode === "rw" ? "read and written" : "read only"}</span></p>
                    {#if f.path}<p class="fact">{f.path}</p>{:else}<FolderPicker bind:value={() => otherFolders[f.name] ?? "", (v) => (otherFolders[f.name] = v)} />{/if}
                  </div>
                {/each}
              </div>
            </section>
          {/if}

          {#if app.agents?.length}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel">
              {@render head("agents", app.agents.length === 1 ? "Its agent" : "Its agents", "What the app runs when you use it. The app brings what each must be (its instructions, form and result); you choose what it runs on.")}
              <div class="space-y-3 pl-9">
                {#each app.agents as need (need.name)}
                  {@const d = need.definition}
                  <div class="space-y-3 rounded-lg border px-3.5 py-3 text-sm" data-testid="install-agent">
                    <p><b class="font-semibold">{d?.agentName ?? need.name}</b> <span class="text-muted-foreground">· {need.description ?? ""}</span></p>
                    {#if given(need)}
                      <p data-testid="install-agent-done"><Check class="mr-1 inline size-4 text-ok" />{agentChoice(agents.find((x) => x.id === need.agentId) ?? ({ id: need.agentId } as Agent), new Map())}</p>
                    {:else if !d}
                      <p class="text-danger">{need.problem ?? "its definition cannot be read"}</p>
                    {:else}
                      {#if fitsOf(need).length}
                        <div class="flex gap-4">
                          <label class="flex items-center gap-2"><input type="radio" class="accent-primary" bind:group={modes[need.name]} value="setup" />Set it up</label>
                          <label class="flex items-center gap-2"><input type="radio" class="accent-primary" bind:group={modes[need.name]} value="fit" data-testid="install-agent-fit" />One of yours that fits</label>
                        </div>
                      {/if}
                      {#if modes[need.name] === "fit"}
                        <NativeSelect.Root class="w-72" bind:value={fitIds[need.name]} data-testid="install-agent-fits">
                          <NativeSelect.Option value="">choose one</NativeSelect.Option>
                          {#each fitsOf(need) as a (a.id)}<NativeSelect.Option value={a.id}>{agentChoice(a, new Map())}</NativeSelect.Option>{/each}
                        </NativeSelect.Root>
                      {:else}
                        {@const c = choices[need.name]!}
                        <ModelAccessPicker bind:value={c.model} area={project?.area ?? null} alone={d.modelAlone ?? false} />
                        {#each toolsAsked(d.addons ?? [], addons).install as addon (addon)}
                          <div class="flex items-center gap-3">
                            <span class="w-44 text-muted-foreground">Tool {addon}</span>
                            <span class="text-warn">not installed: install it from <a class="text-link hover:underline" href={href({ view: "library", shelf: "tools", more: true })}>Library → Tools</a></span>
                          </div>
                        {/each}
                        {#each Object.keys(c.bindings) as addon (addon)}
                          {@const fit = bindings.filter((x) => !x.error && x.addon === addon)}
                          <div class="flex items-center gap-3">
                            <span class="w-44 text-muted-foreground">Configuration of {addon}</span>
                            {#if fit.length}
                              <NativeSelect.Root class="w-56" bind:value={c.bindings[addon]}>
                                {#each fit as x (x.name)}<NativeSelect.Option value={x.name}>{x.name}</NativeSelect.Option>{/each}
                              </NativeSelect.Root>
                            {:else}
                              <span class="text-warn">none yet: make one in <a class="text-link hover:underline" href={href({ view: "addons" })}>Library → Tools</a></span>
                            {/if}
                          </div>
                        {/each}
                        {#each d.knowledge ?? [] as k (k)}
                          <div class="flex items-center gap-3">
                            <span class="w-44 text-muted-foreground">Notes folder</span>
                            <NativeSelect.Root class="w-56" bind:value={c.knowledge[k]}>
                              <NativeSelect.Option value="">choose one ({k})</NativeSelect.Option>
                              {#each folders as f (f)}<NativeSelect.Option value={f}>{f}</NativeSelect.Option>{/each}
                            </NativeSelect.Root>
                          </div>
                        {/each}
                      {/if}
                    {/if}
                  </div>
                {/each}
              </div>
            </section>
          {/if}

          {#if app.secrets?.length}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel">
              {@render head("secrets", "Its secrets", "Kept by Handler, never in the app's folder.")}
              <div class="space-y-2 pl-9 text-sm">
                {#each app.secrets as s (s.name)}
                  <div class="flex items-center gap-3">
                    <span class="fact w-44">{s.name}</span>
                    {#if s.set}<span><Check class="mr-1 inline size-4 text-ok" />kept</span>{:else}<Input type="password" class="w-72" bind:value={secrets[s.name]} data-testid="install-secret" />{/if}
                  </div>
                {/each}
              </div>
            </section>
          {/if}

          {#if app.actions?.length}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="install-actions">
              {@render head("actions", "What you will be able to ask it", "Tried from its page once installed.")}
              <ul class="space-y-1.5 pl-9 text-sm">
                {#each app.actions as action (action.name)}
                  <li class="flex flex-wrap gap-x-3">
                    <span class="font-medium">{action.description}</span>
                    {#if action.examples?.length}<span class="text-muted-foreground">“{action.examples[0]}”</span>{/if}
                    <span class="fact">{action.by === "code" ? "instant" : "takes a while"}</span>
                  </li>
                {/each}
              </ul>
            </section>
          {/if}

          {#if app.suggests?.length}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="install-suggests">
              {@render head("suggests", "Runs by itself", "What the app suggests; off unless you switch it on. You change it any time on its page.")}
              <div class="space-y-2 pl-9 text-sm">
                {#each app.suggests as s, i (i)}
                  {@const made = automations.find((x) => x.name === suggested({ name }, s).name)}
                  <label class="flex items-center gap-3 rounded-lg border px-3 py-2">
                    <span class="min-w-0 flex-1">{s.description} <span class="text-muted-foreground">· {whenSentence(suggested({ name }, s).definition)}</span></span>
                    {#if made}<span class="text-muted-foreground">made ({made.enabled ? "on" : "off"})</span>{:else}<input type="checkbox" class="accent-primary" bind:checked={switched[i]} data-testid="install-suggest" />{/if}
                  </label>
                {/each}
              </div>
            </section>
          {/if}

          {#if showsWho}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel">
              {@render head("who", "Who opens it", "On this computer, and on the paired phones of the people you tick.")}
              <div class="flex flex-wrap gap-2 pl-9 text-sm">
                {#each Object.keys(devicesOf).sort() as person (person)}
                  <label class="flex items-center gap-2 rounded-lg border px-3 py-2 has-checked:border-primary/60 has-checked:bg-primary/5">
                    <input type="checkbox" class="accent-primary" checked={persons?.includes(person) ?? false} onchange={(e) => togglePerson(person, e.currentTarget.checked)} />
                    {person === "owner" ? "you, on your phone" : person}
                  </label>
                {/each}
              </div>
            </section>
          {/if}

          {#if error}<p class="text-sm text-danger" data-testid="install-error">{error}</p>{/if}
          {#if toolbox}
            {@const t = toolbox}
            <ToolboxConfirm changes={t} action="Add and install" onconfirm={() => ((confirmedAdds = t.adds), (toolbox = null), void install())} onback={() => (toolbox = null)} />
          {/if}
          <div class="flex items-center justify-end gap-3">
            {#if doing}<p class="mr-auto text-sm text-muted-foreground" data-testid="install-doing">{doing}…</p>
            {:else if todo.length}<p class="mr-auto text-sm text-warn" data-testid="install-todo">Still to choose: {todo.join("; ")}.</p>
            {:else}<p class="mr-auto text-sm text-muted-foreground">Its tests run first: if they fail, it is not installed (what you chose is kept).</p>{/if}
            <Button variant="ghost" onclick={cancel} data-testid="install-cancel">Cancel</Button>
            <Button disabled={!!doing || todo.length > 0} onclick={install} data-testid="install-go"><Check />Install</Button>
          </div>
        </div>

        <aside class="space-y-2 rounded-[10px] bg-muted/60 px-4 py-3.5 text-sm lg:sticky lg:top-4" data-testid="install-may">
          <h3 class="flex items-center gap-2 font-semibold"><ShieldCheck class="size-4" />It will be allowed to</h3>
          {#each allowed as line (line)}<p class="text-muted-foreground">{line}</p>{/each}
          <p class="pt-1 text-xs text-muted-foreground">Install says yes to this. Nothing of yours is written in the app's folder.</p>
        </aside>
      </div>
    {:else if error}
      <p class="text-sm text-danger">{error}</p>
    {:else}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {/if}
  </div>
</div>
