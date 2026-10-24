<script lang="ts">
  // Setting agents up from their definitions, on one page: those of an agents file being
  // imported (D.23: a project's Add an agent → From a file, `project` preselected; `handler
  // project import-agents`), or the one for one of Handler's needs (D.18, `need`: a helper).
  // Where (a new project, one you have, or outside projects), then each agent asking only what it
  // needs (its models, a configuration of each addon, a knowledge folder for each it reads), what
  // comes with it (skills, checks), and beside it what it will be allowed to do. Set it up creates
  // the agents with their origin (pressing it confirms what they may do, D.8) and ends on them;
  // the file read is then forgotten (Cancel forgets it too). For a need: no project, a folder per
  // session (what a helper that works on copies needs), and the agent is given to it.
  import ShieldAlert from "@lucide/svelte/icons/shield-alert";
  import Check from "@lucide/svelte/icons/check";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import FolderPicker from "../components/FolderPicker.svelte";
  import ModelAccessPicker from "../components/ModelAccessPicker.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import UseChip from "../components/UseChip.svelte";
  import { api } from "../lib/api";
  import { fileOrigin, firstChoice, freeName, missing, mayDo, needOrigin, outsideAgentBody, projectAgentBody, type Choice } from "../lib/setup";
  import type { AddonInfo, Agent, AgentOrigin, AgentsFileAgent, BindingInfo, CreateProjectRequest, HandlerNeed } from "../lib/contracts.gen";
  import { useOfAgent } from "../lib/interface";
  import { projects } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { sessions } from "../lib/sessions.svelte";

  let { file, need: needName, project: intoProject }: { file?: string; need?: string; project?: string } = $props();

  // what is set up: an agents file's agents, or the one agent of a need (its definition)
  type Source = { name: string; description?: string | null; place: "project" | "outside"; agents: AgentsFileAgent[]; origin: (a: AgentsFileAgent) => AgentOrigin };
  let source = $state<Source | null>(null);
  let need = $state<HandlerNeed | null>(null);
  let bindings = $state<BindingInfo[]>([]);
  let addons = $state<AddonInfo[]>([]);
  let folders = $state<string[]>([]);
  let library = $state<string[]>([]); // the skills you have
  let agents = $state<Agent[]>([]);
  let choices = $state<Choice[]>([]);
  let error = $state<string | null>(null);
  let busy = $state(false);

  // where: a new project (its folder and name), one you have, or outside projects
  let place = $state<"new" | "existing" | "outside">("new");
  let folder = $state("");
  let projectName = $state("");
  let projectId = $state("");

  async function load(): Promise<void> {
    try {
      const [b, n, bs, ad, k, sk, ag] = await Promise.all([
        file ? api.agentsFile(file) : null,
        needName ? api.handlerNeeds().then((all) => all.find((x) => x.name === needName) ?? null) : null,
        api.bindings(),
        api.addons(),
        api.knowledge().catch(() => null),
        api.skills(),
        api.agents(),
      ]);
      [bindings, addons, folders, library, agents] = [bs, ad, k?.folders ?? [], sk.map((s) => s.name), ag];
      need = n;
      const found: Source | null = b
        ? { ...b, place: b.place ?? "project", origin: (a) => fileOrigin(b, a.part) }
        : n
          ? { name: n.name, description: n.description, place: "outside", agents: [{ part: n.name, definition: n.definition }], origin: () => needOrigin(n) }
          : null;
      if (!found) throw new Error(`${needName}: no such need of Handler's`);
      choices = found.agents.map((a) => firstChoice(a.definition, bs, folders));
      place = intoProject ? "existing" : found.place === "outside" ? "outside" : "new";
      projectName = found.name;
      projectId = intoProject ?? projects.list[0]?.id ?? "";
      source = found;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void load();
  });

  const project = $derived(place === "existing" ? projects.list.find((p) => p.id === projectId) : undefined);
  const area = $derived(project?.area ?? null);
  const workFolder = $derived(place === "new" ? folder || "the new project's folder" : place === "existing" ? (project?.folder ?? null) : null);
  // the names its agents get: free where they go (a project's names, or outside projects in that folder)
  const taken = $derived(
    place === "existing" && project
      ? project.agents.map((a) => a.name ?? "")
      : place === "outside"
        ? agents.filter((a) => !a.projectId && !a.scope).map((a) => a.name ?? "")
        : [],
  );
  const names = $derived.by(() => {
    const given: string[] = [];
    for (const a of source?.agents ?? []) given.push(freeName(a.definition.agentName, [...taken, ...given]));
    return given;
  });
  const todo = $derived.by(() => {
    const left = (source?.agents ?? []).flatMap((a, i) => missing(a.definition, choices[i]!).map((m) => `${a.definition.agentName}: ${m}`));
    if (place === "new" && !folder) left.unshift("the new project's folder");
    if (place === "existing" && !project) left.unshift("the project");
    return left;
  });
  const skills = $derived([...new Set((source?.agents ?? []).flatMap((a) => a.definition.skills ?? []))]);
  const checks = $derived((source?.agents ?? []).filter((a) => a.checks?.length));
  // the addons whose tools are not built yet: handlerd builds them once an agent uses them (D.4)
  const toPrepare = $derived(
    [...new Set((source?.agents ?? []).flatMap((a) => a.definition.addons ?? []))].filter((n) => addons.some((x) => x.name === n && x.image && !x.imagePresent)),
  );

  /** A configuration of an addon that needs no setting (the app-builder addon): its name, the addon's. */
  async function makeConfiguration(addon: AddonInfo, i: number): Promise<void> {
    try {
      await api.createBinding({ name: addon.name, addon: addon.name, settings: {}, secrets: {} });
      bindings = await api.bindings();
      choices[i]!.bindings[addon.name] = addon.name;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function setUp(): Promise<void> {
    if (!source) return;
    const b = source;
    busy = true;
    error = null;
    const made: Agent[] = [];
    try {
      if (place === "new") {
        const body = {
          folder,
          name: projectName.trim() || null,
          description: b.description ?? null,
          agents: b.agents.map((a, i) => ({ ...projectAgentBody(b.origin(a), a.definition, choices[i]!), name: names[i]!, default: i === 0 })) as CreateProjectRequest["agents"],
        };
        const p = await api.createProject(body);
        await forget();
        await projects.refresh();
        navigate({ view: "project", id: p.id }, true);
        return;
      }
      for (const [i, a] of b.agents.entries()) {
        const named = { name: names[i]! };
        made.push(
          place === "existing" && project
            ? await api.createAgent({ ...projectAgentBody(b.origin(a), a.definition, choices[i]!, project.id), ...named })
            : await api.createAgent({ ...outsideAgentBody(b.origin(a), a.definition, choices[i]!, null), ...named }),
        );
      }
      for (const a of made) sessions.updateAgent(a);
      await forget();
      await projects.refresh();
      if (need && !need.agentId) await api.giveHandlerNeedAgent(need.name, made[0]!.id);
      // back to the feature that needed it, when it has a page of its own
      if (need?.name === "ask-router") navigate({ view: "ask" }, true);
      else if (need?.name === "app-creator") history.back(); // Make your own, Change it: again
      else navigate(project ? { view: "project", id: project.id, agent: made[0]!.id } : { view: "agent", id: made[0]!.id }, true);
    } catch (e) {
      const done = made.length ? ` Set up before it stopped: ${made.map((a) => a.name).join(", ")}.` : "";
      error = `${(e as Error).message}.${done}`;
    } finally {
      busy = false;
    }
  }

  /** A file read for its agents: forgotten once they are set up, or not wanted. */
  async function forget(): Promise<void> {
    if (file) await api.forgetAgentsFile(file).catch(() => undefined);
  }

  async function cancel(): Promise<void> {
    await forget();
    history.back();
  }

  const title = $derived(need ? `Set up the ${need.definition.agentName}` : `Add the agents of ${file}`);
  // where the page was opened from: a helper's Settings, else the project (or Projects)
  const parent = $derived(
    needName
      ? { label: "Helpers", href: href({ view: "settings", section: "helpers" }) }
      : intoProject
        ? { label: projects.list.find((p) => p.id === intoProject)?.name ?? "Project", href: href({ view: "project", id: intoProject }) }
        : { label: "Projects", href: href({ view: "home" }) },
  );
  const from = $derived(needName ? "its definition" : "the file");
</script>

{#snippet step(n: number, heading: string, hint: string)}
  <div class="flex items-start gap-3">
    <span class="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">{n}</span>
    <div><h2 class="text-sm font-semibold">{heading}</h2>{#if hint}<p class="text-sm text-muted-foreground">{hint}</p>{/if}</div>
  </div>
{/snippet}

<PageHeader {title} {parent} titled />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-5xl space-y-6 px-8 py-10">
    <div class="space-y-1">
      <h1 class="text-[1.75rem] leading-tight font-semibold tracking-[-0.022em]">{title}</h1>
      {#if source}<p class="text-sm text-muted-foreground">{#if source.description}{source.description} · {/if}<span class="fact">{needName ? "comes with Handler" : `from ${file}-agents.zip`}</span></p>{/if}
      {#if source && file}
        <p class="flex items-center gap-2 rounded-[10px] border border-warn/40 bg-warn/5 px-3 py-2 text-sm text-warn" data-testid="setup-not-handler"><ShieldAlert class="size-4 shrink-0" />Not from Handler: read what each agent will be allowed to do before you set them up.</p>
      {/if}
    </div>
    {#if source}
      <div class="grid items-start gap-6 lg:grid-cols-[1fr_19rem]">
        <div class="space-y-4">
          {#if !needName}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="setup-where">
              {@render step(1, "Where", "Agents of a project work in its folder; outside projects, each session gets a folder of its own.")}
              <div class="space-y-2 pl-9">
                <label class="flex items-center gap-2.5 rounded-lg border px-3 py-2 text-sm has-checked:border-primary has-checked:bg-primary/5">
                  <input type="radio" class="accent-primary" bind:group={place} value="new" data-testid="setup-place-new" />A new project
                </label>
                {#if place === "new"}
                  <div class="grid gap-3 pl-6 sm:grid-cols-[1fr_14rem]">
                    <div class="space-y-1"><Label class="text-xs">Its folder</Label><FolderPicker bind:value={folder} used={Object.fromEntries(projects.list.map((p) => [p.folder, p.name]))} /></div>
                    <div class="space-y-1"><Label for="setup-project-name" class="text-xs">Its name</Label><Input id="setup-project-name" bind:value={projectName} data-testid="setup-project-name" /></div>
                  </div>
                {/if}
                {#if projects.list.length}
                  <label class="flex items-center gap-2.5 rounded-lg border px-3 py-2 text-sm has-checked:border-primary has-checked:bg-primary/5">
                    <input type="radio" class="accent-primary" bind:group={place} value="existing" data-testid="setup-place-existing" />A project you have
                    {#if place === "existing"}
                      <NativeSelect.Root class="ml-auto w-72" bind:value={projectId} data-testid="setup-project">
                        {#each projects.list as p (p.id)}<NativeSelect.Option value={p.id}>{p.name} · {p.folder}</NativeSelect.Option>{/each}
                      </NativeSelect.Root>
                    {/if}
                  </label>
                {/if}
                <label class="flex items-center gap-2.5 rounded-lg border px-3 py-2 text-sm has-checked:border-primary has-checked:bg-primary/5">
                  <input type="radio" class="accent-primary" bind:group={place} value="outside" data-testid="setup-place-outside" />Outside projects <span class="text-muted-foreground">· a folder per session</span>
                </label>
              </div>
            </section>
          {/if}

          <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel">
            {@render step(needName ? 1 : 2, source.agents.length === 1 ? "Its agent" : "Its agents", `What each needs from you; the rest is ${from}'s, yours to change afterwards in its settings.`)}
            <div class="space-y-3 pl-9">
              {#each source.agents as a, i (a.part)}
                {@const d = a.definition}
                {@const c = choices[i]!}
                <div class="space-y-3 rounded-lg border px-3.5 py-3" data-testid="setup-agent">
                  <p class="flex items-center gap-2 text-sm">
                    <b class="font-semibold">{names[i]}</b><UseChip use={useOfAgent(d)} />
                    {#if d.modelAlone}<span class="rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">the model alone</span>{/if}
                    {#if names[i] !== d.agentName}<span class="text-xs text-muted-foreground">({d.agentName} is taken there)</span>{/if}
                  </p>
                  <ModelAccessPicker bind:value={c.model} {area} alone={d.modelAlone ?? false} />
                  {#each d.addons ?? [] as addon (addon)}
                    {@const fit = bindings.filter((x) => !x.error && x.addon === addon)}
                    {@const info = addons.find((x) => x.name === addon)}
                    <div class="flex items-center gap-3 text-sm">
                      <span class="w-44 text-muted-foreground">Configuration of {addon}</span>
                      {#if fit.length}
                        <NativeSelect.Root class="w-56" bind:value={c.bindings[addon]} data-testid="setup-binding">
                          {#each fit as x (x.name)}<NativeSelect.Option value={x.name}>{x.name}</NativeSelect.Option>{/each}
                        </NativeSelect.Root>
                      {:else if info && !info.settings?.length && !info.secretSlots?.length}
                        <span class="text-warn">none yet</span>
                        <Button size="sm" variant="outline" onclick={() => makeConfiguration(info, i)} data-testid="setup-addon-make">Make one</Button>
                        <span class="text-xs text-muted-foreground">(it needs no setting)</span>
                      {:else}
                        <span class="text-warn">none yet: make one in <a class="text-link hover:underline" href={href({ view: "addons" })}>Library → Addons</a>, then come back</span>
                      {/if}
                    </div>
                  {/each}
                  {#each d.knowledge ?? [] as k (k)}
                    <div class="flex items-center gap-3 text-sm">
                      <span class="w-44 text-muted-foreground">Knowledge folder</span>
                      <NativeSelect.Root class="w-56" bind:value={c.knowledge[k]} data-testid="setup-knowledge">
                        <NativeSelect.Option value="">choose one ({k} in {from})</NativeSelect.Option>
                        {#each folders as f (f)}<NativeSelect.Option value={f}>{f}</NativeSelect.Option>{/each}
                      </NativeSelect.Root>
                    </div>
                  {/each}
                </div>
              {/each}
            </div>
          </section>

          {#if skills.length || checks.length || toPrepare.length}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="setup-comes">
              {@render step(needName ? 2 : 3, "Comes with it", "")}
              <div class="space-y-1.5 pl-9 text-sm">
                {#if skills.length}
                  {@const have = skills.filter((s) => library.includes(s))}
                  <p>Skills {skills.join(", ")} <span class="text-muted-foreground">· added to your Skills{have.length ? `; you have ${have.join(", ")}: yours are kept` : ""}</span></p>
                {/if}
                {#each checks as a (a.part)}
                  <p>{a.checks?.length} check{a.checks?.length === 1 ? "" : "s"} for {a.definition.agentName} <span class="text-muted-foreground">· run them once it is set up</span></p>
                {/each}
                {#each toPrepare as addon (addon)}
                  <p data-testid="setup-prepare">The {addon} tools <span class="text-muted-foreground">· prepared once on this computer, a few minutes, as soon as it is set up</span></p>
                {/each}
              </div>
            </section>
          {/if}

          {#if error}<p class="text-sm text-danger" data-testid="setup-error">{error}</p>{/if}
          <div class="flex items-center justify-end gap-3">
            {#if todo.length}<p class="mr-auto text-sm text-warn" data-testid="setup-todo">Still to choose: {todo.join("; ")}.</p>{:else}<p class="mr-auto text-sm text-muted-foreground">Nothing follows {from} afterwards: the agents are yours.</p>{/if}
            <Button variant="ghost" onclick={cancel} data-testid="setup-cancel">Cancel</Button>
            <Button disabled={busy || todo.length > 0} onclick={setUp} data-testid="setup-go"><Check />Set it up</Button>
          </div>
        </div>

        <aside class="space-y-2 rounded-[10px] bg-muted/60 px-4 py-3.5 text-sm lg:sticky lg:top-4" data-testid="setup-may">
          <h3 class="flex items-center gap-2 font-semibold"><ShieldCheck class="size-4" />It will be allowed to</h3>
          {#each source.agents as a, i (a.part)}
            <div><b class="font-medium">{names[i]}:</b> <span class="text-muted-foreground">{mayDo(a.definition, workFolder).join("; ")}</span></div>
          {/each}
          <p class="pt-1 text-xs text-muted-foreground">Set it up says yes to this. Change any of it later in the agent's settings.</p>
        </aside>
      </div>
    {:else if !error}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {:else}
      <p class="text-sm text-danger">{error}</p>
    {/if}
  </div>
</div>
