<script lang="ts">
  // Addons (G): an addon brings programs, the skills that explain them, maybe an MCP server, and
  // asks for settings and secrets; a configuration is one set of them (in the files and the API:
  // a binding), what an agent is given. The page follows the three steps it states: install an
  // addon (AddonInstaller, which goes on to step 2 once one is installed), configure it
  // (BindingForm, in its card), give a configuration to an agent (in the agent's settings, which
  // each configuration's line points to while nothing uses it). Configurations are renamed and
  // deleted only while nothing selects them; a project may keep one to itself.
  import Plus from "@lucide/svelte/icons/plus";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { AddonInfo, BindingInfo, BindingRequest } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import AddonInstaller from "./AddonInstaller.svelte";
  import BindingForm from "./BindingForm.svelte";
  import LoadingCards from "./LoadingCards.svelte";

  // the form open: a new binding of an addon, or a binding being edited
  type Panel = { kind: "new"; addon: string } | { kind: "edit"; name: string };
  let addons = $state<AddonInfo[]>([]);
  let bindings = $state<BindingInfo[]>([]);
  let loaded = $state(false); // the first answer came
  let panel = $state<Panel | null>(null);
  let error = $state<string | null>(null);
  let notice = $state<string | null>(null); // what the last install did
  let installer = $state<AddonInstaller | null>(null);

  const orphans = $derived(bindings.filter((b) => !addons.some((a) => a.name === b.addon)));
  const STEPS = [
    "Install an addon",
    "Configure it: its store, account or settings",
    "Give a configuration to an agent, in the agent's settings",
  ];

  async function load(): Promise<void> {
    try {
      [addons, bindings] = await Promise.all([api.addons(), api.bindings()]);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loaded = true;
    }
  }

  async function run(action: () => Promise<unknown>): Promise<void> {
    error = null;
    try {
      await action();
      panel = null;
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  /** `base`, or `base-2`, `base-3`… when a binding has it. */
  function freeName(base: string): string {
    let name = base;
    for (let i = 2; bindings.some((b) => b.name === name); i++) name = `${base}-${i}`;
    return name;
  }

  /** Where an addon comes from, as its card says it. */
  function origin(a: AddonInfo): string {
    if (a.builtin) return "built-in";
    if (a.source?.startsWith("catalog:")) return a.overridesBuiltin ? "from the catalog, in place of the built-in one" : "from the catalog";
    return a.overridesBuiltin ? "yours, in place of the built-in one" : "yours";
  }

  const create = (body: BindingRequest) => run(() => api.createBinding(body));
  const update = (name: string, body: BindingRequest) => run(() => api.updateBinding(name, body));
  const remove = (name: string) => confirm(`Delete the configuration ${name} and its secrets?`) && run(() => api.deleteBinding(name));

  const removeAddon = (name: string) =>
    confirm(`Uninstall ${name}? Its folder and its image go; no configuration may use it.`) && run(() => api.removeAddon(name));

  /** Installed: on to step 2, its first configuration's form, in its card. */
  async function installed(message: string, addon: string): Promise<void> {
    notice = message;
    await load();
    panel = { kind: "new", addon };
    requestAnimationFrame(() => document.getElementById(`addon-${addon}`)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  $effect(() => {
    void load();
  });
</script>

<section class="space-y-8" data-testid="addons">
  <div class="space-y-3">
    <p class="max-w-2xl text-sm text-muted-foreground">
      Programs your agents can use beyond the agent program itself, with the skills that explain them: a web browser, the Shopify CLI… An
      agent gets an addon through one of its configurations (its settings and secrets, e.g. one per store). Optional: agents work
      without addons.
    </p>
    <ol class="flex flex-wrap gap-x-6 gap-y-1.5 text-sm" data-testid="addons-steps">
      {#each STEPS as step, i (step)}
        <li class="flex items-center gap-2">
          <span class="flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-xs text-muted-foreground">{i + 1}</span>{step}
        </li>
      {/each}
    </ol>
  </div>

  <div class="space-y-3">
    <h2 class="text-base font-semibold">Installed</h2>
    {#if error}<p class="text-sm text-danger" data-testid="binding-error">{error}</p>{/if}
    {#if notice}<p class="text-sm" data-testid="addon-notice">{notice}</p>{/if}
    <div class="grid items-start gap-3 md:grid-cols-2">
      {#each addons as a (a.name)}
        {@const configurations = bindings.filter((b) => b.addon === a.name)}
        <div class="scroll-mt-6 space-y-2.5 rounded-lg border bg-card p-3.5 text-sm" id="addon-{a.name}" data-testid="addon-card">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <div class="font-medium">
                {a.name}
                <span class="ml-1 text-xs font-normal text-muted-foreground" data-testid="addon-origin" title={a.directory}>{origin(a)}</span>
              </div>
              {#if a.description}<div class="text-xs text-muted-foreground">{a.description}</div>{/if}
              {#if a.commands?.length || a.skills?.length}
                <div class="text-xs text-muted-foreground" data-testid="addon-contents">
                  {[a.commands?.length ? `programs: ${a.commands.join(", ")}` : "", a.skills?.length ? `skills: ${a.skills.join(", ")}` : ""].filter(Boolean).join(" · ")}
                </div>
              {/if}
              {#if !a.builtin && !a.source?.startsWith("catalog:")}
                <div class="truncate font-mono text-xs text-muted-foreground" title={a.directory}>{a.directory}</div>
                {#if a.source}<div class="truncate text-xs text-muted-foreground" data-testid="addon-source-line">installed from <span class="font-mono">{a.source}</span></div>{/if}
              {/if}
            </div>
            {#if a.image && !a.imagePresent}
              <a class="shrink-0 text-xs text-warn hover:underline" href={href({ view: "settings", section: "images" })} title="its image, in Settings → Images">
                image not built yet →
              </a>
            {/if}
          </div>
          {#if a.updateAvailable}
            <p class="flex items-center gap-2 text-xs" data-testid="addon-source-line">
              An update is in the catalog.
              <Button variant="outline" size="sm" onclick={() => installer?.look(a.source ?? "")} data-testid="addon-update">See the update</Button>
            </p>
          {/if}
          {#if a.error}
            <p class="text-xs text-danger">invalid: {a.error}</p>
          {:else}
            {#if configurations.length}
              <ul class="space-y-1.5">
                {#each configurations as b (b.name)}
                  {#if panel?.kind === "edit" && panel.name === b.name}
                    <li><BindingForm addon={a} start={b.name} editing={b} onsave={(body) => update(b.name, body)} oncancel={() => (panel = null)} /></li>
                  {:else}
                    <li class="rounded-md border bg-background px-2.5 py-1.5" data-testid="binding-row">
                      <div class="flex items-center justify-between gap-2">
                        <span class="min-w-0 truncate">
                          <span class="font-medium">{b.name}</span>
                          {#if b.description}<span class="text-xs text-muted-foreground"> — {b.description}</span>{/if}
                        </span>
                        <span class="flex shrink-0 gap-1">
                          {#if !b.error}
                            <Button variant="ghost" size="sm" onclick={() => (panel = { kind: "edit", name: b.name })} data-testid="binding-edit">Edit</Button>
                          {/if}
                          {#if !b.usedBy?.length}
                            <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={() => remove(b.name)} data-testid="binding-delete">Delete</Button>
                          {/if}
                        </span>
                      </div>
                      {#if b.error}
                        <p class="text-xs text-danger">invalid: {b.error}</p>
                      {:else if Object.keys(b.settings ?? {}).length || b.secrets?.length}
                        <p class="font-mono text-xs text-muted-foreground">
                          {[...Object.entries(b.settings ?? {}).map(([k, v]) => `${k}=${v}`), ...(b.secrets ?? []).map((s) => `${s}=•••`)].join("  ")}
                        </p>
                      {/if}
                      <p class="truncate text-xs text-muted-foreground" title={b.usedBy?.join(", ")} data-testid="binding-use">
                        {b.usedBy?.length ? `used by ${b.usedBy.join(", ")}` : "not used yet: give it to an agent in the agent's settings"}
                      </p>
                    </li>
                  {/if}
                {/each}
              </ul>
            {/if}
            {#if panel?.kind === "new" && panel.addon === a.name}
              <BindingForm addon={a} start={freeName(a.name)} onsave={create} oncancel={() => (panel = null)} />
            {:else}
              <div class="flex flex-wrap items-center gap-1">
                <Button variant="outline" size="sm" onclick={() => (panel = { kind: "new", addon: a.name })} data-testid="new-binding">
                  <Plus />{configurations.length ? "Another configuration" : "Configure"}
                </Button>
                {#if !configurations.length}<span class="ml-1 text-xs text-muted-foreground">not configured yet</span>{/if}
                {#if a.source}
                  <span class="ml-auto flex gap-1">
                    {#if !a.updateAvailable}
                      <Button variant="ghost" size="sm" class="text-muted-foreground" onclick={() => installer?.look(a.source ?? "")} data-testid="addon-update">Reinstall</Button>
                    {/if}
                    <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={() => removeAddon(a.name)} data-testid="addon-remove">Uninstall</Button>
                  </span>
                {/if}
              </div>
            {/if}
          {/if}
        </div>
      {:else}
        {#if !loaded}<LoadingCards />{/if}
      {/each}
    </div>
    {#each orphans as b (b.name)}
      <p class="text-xs text-danger" data-testid="binding-row">configuration {b.name}: {b.error ?? `unknown addon ${b.addon}`}</p>
    {/each}
  </div>

  <AddonInstaller bind:this={installer} oninstalled={installed} />
</section>
