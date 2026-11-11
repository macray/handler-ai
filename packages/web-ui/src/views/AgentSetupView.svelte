<script lang="ts">
  // Setting agents up from their definitions, on one page: those of an agents file being
  // imported (D.23: a project's Add an agent → From a file, `project` preselected; `handler
  // project import-agents`). Where (a new project, one you have, or outside projects), then each
  // agent asking only what it needs (its models, a configuration of each addon, a knowledge
  // folder for each it reads), what comes with it (skills, checks, the tools it needs that a source
  // offers, G.5), and beside it what it will be allowed to do (in amber what weakens its sandbox).
  // Set it up installs those tools, then creates the agents with their origin (pressing it
  // confirms what they and the tools may do, D.8) and ends on them; the file read is then
  // forgotten (Cancel forgets it too). A tool no source can bring along blocks it, said in the
  // agent's card.
  // Handler's helpers are set up by their card instead (HelperCard).
  import CircleAlert from "@lucide/svelte/icons/circle-alert";
  import Wrench from "@lucide/svelte/icons/wrench";
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
  import { api, toolboxChanges, type ToolboxChanges } from "../lib/api";
  import ToolboxConfirm from "../components/ToolboxConfirm.svelte";
  import { comesAlong, fileOrigin, firstChoice, missing, mayDo, outsideAgentBody, projectAgentBody, toolsAsked, weakens, type Choice } from "../lib/setup";
  import { fromWords, offered } from "../lib/sources";
  import { freeName } from "../lib/text";
  import type { AddonInfo, AddonPreview, Agent, AgentOrigin, AgentsFileAgent, BindingInfo, CreateProjectRequest } from "../lib/contracts.gen";
  import { useOfAgent } from "../lib/interface";
  import { projects } from "../lib/projects.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { sessions } from "../lib/sessions.svelte";

  let { file, project: intoProject }: { file: string; project?: string } = $props();

  // what is set up: an agents file's agents
  type Source = { name: string; description?: string | null; place: "project" | "outside"; agents: AgentsFileAgent[]; origin: (a: AgentsFileAgent) => AgentOrigin };
  let source = $state<Source | null>(null);
  let bindings = $state<BindingInfo[]>([]);
  let addons = $state<AddonInfo[]>([]);
  let folders = $state<string[]>([]);
  let library = $state<string[]>([]); // the skills you have
  let agents = $state<Agent[]>([]);
  let choices = $state<Choice[]>([]);
  let error = $state<string | null>(null);
  let busy = $state(false);
  let toolbox = $state<ToolboxChanges | null>(null); // what setting it up adds to the toolbox
  let confirmedAdds: string[] = []; // confirmed, sent with every agent (B.6)
  let madeBefore: Agent[] = []; // set up before it stopped for the toolbox: not again
  // the tools its agents need, not installed, that a source offers: what installing each brings
  let offers = $state<Record<string, { preview: AddonPreview; from: string }>>({});

  // where: a new project (its folder and name), one you have, or outside projects
  let place = $state<"new" | "existing" | "outside">("new");
  let folder = $state("");
  let projectName = $state("");
  let projectId = $state("");

  async function load(): Promise<void> {
    try {
      const [b, bs, ad, k, sk, ag, so] = await Promise.all([
        api.agentsFile(file),
        api.bindings(),
        api.addons(),
        api.knowledge().catch(() => null),
        api.skills(),
        api.agents(),
        api.sources().catch(() => []),
      ]);
      const lacking = [...new Set(b.agents.flatMap((a) => toolsAsked(a.definition.addons ?? [], ad).install))];
      const onOffer = offered(so, "addon").filter((o) => lacking.includes(o.item.name) && !o.item.installed);
      // the first source offering each (Handler's first, as the sources are listed); one whose
      // preview cannot be read is not offered
      const seen = await Promise.all(
        lacking.map(async (n) => {
          const o = onOffer.find((x) => x.item.name === n);
          const preview = o ? await api.previewAddon(`source:${o.source.id}/${n}`).catch(() => null) : null;
          return o && preview ? ([n, { preview, from: fromWords(o.source) }] as const) : null;
        }),
      );
      offers = Object.fromEntries(seen.filter((x) => x !== null));
      [bindings, addons, folders, library, agents] = [bs, ad, k?.folders ?? [], sk.map((s) => s.name), ag];
      const found: Source = { ...b, place: b.place ?? "project", origin: (a) => fileOrigin(b, a.part) };
      choices = found.agents.map((a) => firstChoice(a.definition, bs, ad, folders));
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
    for (const a of source?.agents ?? []) given.push(freeName(a.definition.agentName, [...taken, ...given], " "));
    return given;
  });
  // the tools installed with it, and those it cannot be set up without (none of your sources has
  // them, or they are used through a connection, made in Library → Tools first)
  const comingTools = $derived(Object.keys(offers).filter((n) => comesAlong(offers[n]!.preview) && !addons.some((a) => a.name === n)));
  const blocking = $derived([...new Set((source?.agents ?? []).flatMap((a) => toolsAsked(a.definition.addons ?? [], addons).install))].filter((n) => !comingTools.includes(n)));
  const todo = $derived.by(() => {
    const left = (source?.agents ?? []).flatMap((a, i) =>
      missing(a.definition, choices[i]!, addons, [...comingTools, ...blocking]).map((m) => (several ? `${a.definition.agentName}: ${m}` : m)),
    );
    if (place === "new" && !folder) left.unshift("the new project's folder");
    if (place === "existing" && !project) left.unshift("the project");
    return left;
  });
  const several = $derived((source?.agents.length ?? 0) > 1);
  const skills = $derived([...new Set((source?.agents ?? []).flatMap((a) => a.definition.skills ?? []))]);
  const checks = $derived((source?.agents ?? []).filter((a) => a.checks?.length));
  // the addons whose tools are not built yet: handlerd builds them once an agent uses them (D.4)
  const toPrepare = $derived(
    [...new Set((source?.agents ?? []).flatMap((a) => a.definition.addons ?? []))].filter((n) => addons.some((x) => x.name === n && x.image && !x.imagePresent)),
  );

  async function setUp(): Promise<void> {
    if (!source) return;
    const b = source;
    busy = true;
    error = null;
    toolbox = null;
    const made: Agent[] = [...madeBefore];
    const toolboxAdds = confirmedAdds;
    try {
      // the tools it brings along first, each as previewed, with what it adds to the toolbox
      // (said under Comes with it): its agents are saved using them
      for (const n of comingTools) {
        const p = offers[n]!.preview;
        await api.installAddon(p.source, p.digest, (p.toolbox?.adds ?? []).map((a) => a.name));
      }
      if (comingTools.length) addons = await api.addons();
      if (place === "new") {
        const body = {
          toolboxAdds,
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
        if (i < made.length) continue;
        const named = { name: names[i]!, toolboxAdds };
        made.push(
          place === "existing" && project
            ? await api.createAgent({ ...projectAgentBody(b.origin(a), a.definition, choices[i]!, project.id), ...named })
            : await api.createAgent({ ...outsideAgentBody(b.origin(a), a.definition, choices[i]!, null), ...named }),
        );
      }
      for (const a of made) sessions.updateAgent(a);
      await forget();
      await projects.refresh();
      navigate(project ? { view: "project", id: project.id, agent: made[0]!.id } : { view: "agent", id: made[0]!.id }, true);
    } catch (e) {
      if ((toolbox = toolboxChanges(e))) {
        madeBefore = made;
        return;
      }
      const done = made.length ? ` Set up before it stopped: ${made.map((a) => a.name).join(", ")}.` : "";
      error = `${(e as Error).message}.${done}`;
    } finally {
      busy = false;
    }
  }

  /** A file read for its agents: forgotten once they are set up, or not wanted. */
  async function forget(): Promise<void> {
    await api.forgetAgentsFile(file).catch(() => undefined);
  }

  async function cancel(): Promise<void> {
    await forget();
    history.back();
  }

  const title = $derived(source?.agents.length === 1 ? `Set up ${source.agents[0]!.definition.agentName}` : `Set up the agents of ${file}`);
  const go = $derived(comingTools.length ? `Install ${comingTools.join(", ")} and set it up` : "Set it up");
  // where the page was opened from: the project (or Projects)
  const parent = $derived(
    intoProject
      ? { label: projects.list.find((p) => p.id === intoProject)?.name ?? "Project", href: href({ view: "project", id: intoProject }) }
      : { label: "Projects", href: href({ view: "projects" }) },
  );
  const from = "the file";
</script>

{#snippet step(n: number, heading: string, hint: string)}
  <div class="flex items-start gap-3">
    <span class="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">{n}</span>
    <div><h2 class="text-sm font-semibold">{heading}</h2>{#if hint}<p class="text-sm text-muted-foreground">{hint}</p>{/if}</div>
  </div>
{/snippet}

<PageHeader width="max-w-5xl" {title} {parent} />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-5xl space-y-6 px-8 py-10">
    {#if source}<p class="text-sm text-muted-foreground">{#if source.description}{source.description} · {/if}<span class="fact">from {file}-agents.zip</span></p>{/if}
    {#if source}
      <div class="grid items-start gap-6 lg:grid-cols-[1fr_19rem]">
        <div class="space-y-4">
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

          <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel">
            {@render step(2, source.agents.length === 1 ? "Its agent" : "Its agents", `What each needs from you; the rest is ${from}'s, yours to change afterwards in its settings.`)}
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
                  {#each toolsAsked(d.addons ?? [], addons).install.filter((n) => blocking.includes(n)) as addon (addon)}
                    {@const offer = offers[addon]}
                    <div class="flex items-start gap-3 rounded-lg border border-danger/30 bg-danger/5 p-3 text-sm" data-testid="setup-tool-missing">
                      <CircleAlert class="mt-0.5 size-4 shrink-0 text-danger" />
                      {#if offer}
                        <p><b class="font-semibold">Needs the {addon} tool, used through a connection</b><br /><span class="text-muted-foreground">Install it and make its connection in <a class="text-link hover:underline" href={href({ view: "library", shelf: "tools", more: true, install: offer.preview.source })}>Library → Tools</a>, then come back.</span></p>
                      {:else}
                        <p><b class="font-semibold">Needs the {addon} tool, which none of your sources has</b><br /><span class="text-muted-foreground">Add the source it comes from in <a class="text-link hover:underline" href={href({ view: "settings", section: "sources" })}>Settings → Sources</a>, or install it from a folder in <a class="text-link hover:underline" href={href({ view: "library", shelf: "tools", more: true })}>Library → Tools</a>, then come back.</span></p>
                      {/if}
                    </div>
                  {/each}
                  <ModelAccessPicker bind:value={c.model} {area} alone={d.modelAlone ?? false} />
                  {#each (d.addons ?? []).filter((n) => comingTools.includes(n)) as addon (addon)}
                    <div class="flex items-start gap-3 rounded-lg bg-muted/60 p-3 text-sm" data-testid="setup-tool-comes">
                      <Wrench class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                      <p class="mr-auto"><b class="font-semibold">Uses the {addon} tool</b> <span class="fact">{offers[addon]!.from}</span>{#if offers[addon]!.preview.description}<br /><span class="text-muted-foreground">{offers[addon]!.preview.description}</span>{/if}</p>
                      <span class="shrink-0 rounded-full border px-2 py-0.5 text-xs text-muted-foreground">installed with it</span>
                    </div>
                  {/each}
                  {#each Object.keys(c.bindings) as addon (addon)}
                    {@const fit = bindings.filter((x) => !x.error && x.addon === addon)}
                    <div class="flex items-center gap-3 text-sm">
                      <span class="w-44 text-muted-foreground">Configuration of {addon}</span>
                      {#if fit.length}
                        <NativeSelect.Root class="w-56" bind:value={c.bindings[addon]} data-testid="setup-binding">
                          {#each fit as x (x.name)}<NativeSelect.Option value={x.name}>{x.name}</NativeSelect.Option>{/each}
                        </NativeSelect.Root>
                      {:else}
                        <span class="text-warn">none yet: make one in <a class="text-link hover:underline" href={href({ view: "addons" })}>Library → Tools</a>, then come back</span>
                      {/if}
                    </div>
                  {/each}
                  {#each d.knowledge ?? [] as k (k)}
                    <div class="flex items-center gap-3 text-sm">
                      <span class="w-44 text-muted-foreground">Notes folder</span>
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

          {#if skills.length || checks.length || toPrepare.length || comingTools.length}
            <section class="space-y-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="setup-comes">
              {@render step(3, "Comes with it", "")}
              <div class="space-y-1.5 pl-9 text-sm">
                {#if skills.length}
                  {@const have = skills.filter((s) => library.includes(s))}
                  <p>Skills {skills.join(", ")} <span class="text-muted-foreground">· added to your Skills{have.length ? `; you have ${have.join(", ")}: yours are kept` : ""}</span></p>
                {/if}
                {#each checks as a (a.part)}
                  <p>{a.checks?.length} check{a.checks?.length === 1 ? "" : "s"} for {a.definition.agentName} <span class="text-muted-foreground">· run them once it is set up</span></p>
                {/each}
                {#each comingTools as addon (addon)}
                  {@const adds = (offers[addon]!.preview.toolbox?.adds ?? []).map((a) => a.name)}
                  <p data-testid="setup-tool-installed">The {addon} tool <span class="text-muted-foreground">· {offers[addon]!.from}</span></p>
                  {#if adds.length}<p>{adds.join(", ")} in the toolbox <span class="text-muted-foreground">· for {addon}, the system every agent works in: added, then the toolbox is rebuilt</span></p>{/if}
                {/each}
                {#each toPrepare as addon (addon)}
                  <p data-testid="setup-prepare">The {addon} tools <span class="text-muted-foreground">· prepared once on this computer, a few minutes, as soon as it is set up</span></p>
                {/each}
              </div>
            </section>
          {/if}

          {#if error}<p class="text-sm text-danger" data-testid="setup-error">{error}</p>{/if}
          {#if toolbox}
            {@const t = toolbox}
            <ToolboxConfirm changes={t} {busy} action="Add and set it up" onconfirm={() => ((confirmedAdds = t.adds), void setUp())} onback={() => (toolbox = null)} />
          {/if}
          <div class="flex items-center justify-end gap-3">
            {#if blocking.length}
              <p class="mr-auto flex items-center gap-2 text-sm text-danger" data-testid="setup-blocked"><CircleAlert class="size-4 shrink-0" />Can't set it up without the {blocking.join(", ")} tool{blocking.length > 1 ? "s" : ""}</p>
            {:else if todo.length}
              <p class="mr-auto text-sm text-muted-foreground" data-testid="setup-todo">{todo.length} left: {todo.join(" · ")}</p>
            {:else}
              <p class="mr-auto text-sm text-muted-foreground">Nothing follows {from} afterwards: the agents are yours.</p>
            {/if}
            <Button variant="ghost" onclick={cancel} data-testid="setup-cancel">Cancel</Button>
            <Button disabled={busy || todo.length > 0 || blocking.length > 0} onclick={setUp} data-testid="setup-go"><Check />{go}</Button>
          </div>
        </div>

        <aside class="space-y-2 rounded-[10px] bg-muted/60 px-4 py-3.5 text-sm lg:sticky lg:top-4" data-testid="setup-may">
          <h3 class="flex items-center gap-2 font-semibold"><ShieldCheck class="size-4" />It will be allowed to</h3>
          {#each source.agents as a, i (a.part)}
            <div>
              <b class="font-medium">{names[i]}</b>
              <ul class="mt-0.5 space-y-0.5">
                {#each mayDo(a.definition, workFolder) as may (may)}
                  <li class={weakens(may) ? "text-warn" : "text-muted-foreground"}>{may}</li>
                {/each}
                {#each (a.definition.addons ?? []).filter((n) => comingTools.includes(n) && offers[n]!.preview.egress?.length) as addon (addon)}
                  {@const hosts = offers[addon]!.preview.egress ?? []}
                  <li class="text-muted-foreground" data-testid="setup-tool-hosts">
                    <details>
                      <summary class="cursor-pointer">for the {addon} tool, reach {hosts.length} host{hosts.length > 1 ? "s" : ""}</summary>
                      <p class="fact mt-1 break-words">{hosts.join(" · ")}</p>
                    </details>
                  </li>
                {/each}
              </ul>
            </div>
          {/each}
          <p class="pt-1 text-xs text-muted-foreground">{go} says yes to this. Change any of it later in the agent's settings.</p>
        </aside>
      </div>
    {:else if !error}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {:else}
      <p class="text-sm text-danger">{error}</p>
    {/if}
  </div>
</div>
