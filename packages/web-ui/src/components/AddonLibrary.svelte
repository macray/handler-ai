<script lang="ts">
  // Addons (G): an addon brings programs, the skills that explain them, maybe an MCP server, and
  // asks for settings and secrets; a configuration is one set of them (in the files and the API:
  // a binding), what an agent is given. Nothing configured yet: the three steps (install an
  // addon, configure it, give a configuration to an agent in its settings). Then a list, each
  // addon with its configurations under it; installing (AddonInstaller), a configuration
  // (BindingForm) and an addon's details (where it comes from, what it reaches, its uninstall) in
  // dialogs. What uses a configuration is said in its Edit; one is deleted only while nothing
  // selects it. `install` (from Discover, D.26): that source's preview opens at once.
  import Plus from "@lucide/svelte/icons/plus";
  import Puzzle from "@lucide/svelte/icons/puzzle";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { AddonInfo, BindingInfo, BindingRequest } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import AddonInstaller from "./AddonInstaller.svelte";
  import BindingForm from "./BindingForm.svelte";
  import Dialog from "./Dialog.svelte";
  import LoadingCards from "./LoadingCards.svelte";

  // the dialog open: a new configuration of an addon, one being edited, or an addon's details
  type Panel = { kind: "new"; addon: string } | { kind: "edit"; name: string } | { kind: "details"; addon: string };
  let addons = $state<AddonInfo[]>([]);
  let bindings = $state<BindingInfo[]>([]);
  let loaded = $state(false); // the first answer came
  let panel = $state<Panel | null>(null);
  let error = $state<string | null>(null);
  let notice = $state<string | null>(null); // what the last install did
  let installer = $state<AddonInstaller | null>(null);
  let { install }: { install?: string } = $props();
  let looked: string | undefined;

  $effect(() => {
    if (install && installer && looked !== install) {
      looked = install;
      void installer.look(install);
    }
  });

  const orphans = $derived(bindings.filter((b) => !addons.some((a) => a.name === b.addon)));
  // the dialog's addon and configuration
  const binding = $derived.by(() => {
    const p = panel;
    return p?.kind === "edit" ? bindings.find((b) => b.name === p.name) : undefined;
  });
  const addon = $derived.by(() => {
    const p = panel;
    const name = p === null ? undefined : p.kind === "edit" ? binding?.addon : p.addon;
    return addons.find((a) => a.name === name);
  });

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
      notice = null;
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  function open(next: Panel): void {
    error = null;
    panel = next;
  }

  /** `base`, or `base-2`, `base-3`… when a binding has it. */
  function freeName(base: string): string {
    let name = base;
    for (let i = 2; bindings.some((b) => b.name === name); i++) name = `${base}-${i}`;
    return name;
  }

  /** Where an addon comes from, in a few words. */
  function origin(a: AddonInfo): string {
    if (a.builtin) return "built-in";
    if (a.source?.startsWith("source:")) {
      const id = a.source.slice("source:".length).split("/")[0];
      const from = id === "official" ? "from Handler" : `from ${id}`;
      return a.overridesBuiltin ? `${from}, in place of the built-in` : from;
    }
    return a.overridesBuiltin ? "yours, in place of the built-in" : "yours";
  }

  /** What it brings, in one line. */
  const brings = (a: AddonInfo) =>
    [a.commands?.length ? `programs: ${a.commands.join(", ")}` : "", a.skills?.length ? `skills: ${a.skills.join(", ")}` : ""].filter(Boolean).join(" · ");
  /** A configuration's values, secrets hidden. */
  const values = (b: BindingInfo) =>
    [...Object.entries(b.settings ?? {}).map(([k, v]) => `${k}=${v}`), ...(b.secrets ?? []).map((x) => `${x}=•••`)].join("  ");

  const create = (body: BindingRequest) => run(() => api.createBinding(body));
  const update = (name: string, body: BindingRequest) => run(() => api.updateBinding(name, body));
  const remove = (name: string) => confirm(`Delete the configuration ${name} and its secrets?`) && run(() => api.deleteBinding(name));

  const removeAddon = (name: string) =>
    confirm(`Uninstall ${name}? Its folder and its image go; no configuration may use it.`) && run(() => api.removeAddon(name));

  /** Installed: on to step 2, its first configuration's dialog. */
  async function installed(message: string, name: string): Promise<void> {
    notice = message;
    await load();
    open({ kind: "new", addon: name });
  }

  $effect(() => {
    void load();
  });
</script>

{#snippet step(n: number, title: string, text: string)}
  <li class="flex gap-3">
    <span class="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted font-mono text-xs text-muted-foreground">{n}</span>
    <div class="space-y-0.5 pt-0.5">
      <p class="font-medium">{title}</p>
      <p class="text-muted-foreground">{text}</p>
    </div>
  </li>
{/snippet}

{#snippet installButton(primary: boolean)}
  {@const more = installer?.count() ?? 0}
  <Button variant={primary ? "default" : "outline"} size="sm" onclick={() => installer?.open()} data-testid="addon-elsewhere">
    <Plus />Install an addon{#if more}<span class="ml-0.5 rounded-full bg-black/10 px-1.5 text-xs font-normal">{more}</span>{/if}
  </Button>
{/snippet}

<section class="space-y-10" data-testid="addons">
  {#if loaded && !bindings.length}
    <!-- nothing configured yet: what addons are for, and the three steps -->
    <div class="enter rounded-[10px] border bg-card p-6 shadow-panel" data-testid="addons-steps">
      <div class="flex items-start gap-4">
        <span class="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Puzzle class="size-5" /></span>
        <div class="space-y-1">
          <h2 class="text-base font-semibold">Give your agents more tools</h2>
          <p class="max-w-xl text-sm text-muted-foreground">
            Programs beyond the agent program itself, with the skills that explain them: a web browser, the Shopify CLI, apps. Optional:
            agents work without addons.
          </p>
        </div>
      </div>
      <ol class="mt-6 space-y-4 text-sm sm:pl-14">
        {@render step(1, "Install an addon", "From Handler's source, one you added, or a folder of your own. You see what it brings first.")}
        {@render step(2, "Configure it", "Its settings and secrets: a store, an account. One addon can have several configurations, e.g. one per store.")}
        {@render step(3, "Give a configuration to an agent", "In the agent's settings: it then has the programs, and only the hosts the addon needs.")}
      </ol>
      <div class="mt-6 flex flex-wrap items-center gap-2 sm:pl-14">
        {@render installButton(true)}
        {#if addons.length}<span class="text-xs text-muted-foreground">or configure one installed below.</span>{/if}
      </div>
    </div>
  {/if}

  <div class="space-y-4">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div class="space-y-1">
        <h2 class="text-base font-semibold">Installed</h2>
        <p class="max-w-2xl text-sm text-muted-foreground">An agent gets an addon through one of its configurations, given in the agent's settings.</p>
      </div>
      {#if bindings.length}{@render installButton(false)}{/if}
    </div>
    {#if error && !panel}<p class="text-sm text-danger" data-testid="binding-error">{error}</p>{/if}
    {#if notice}<p class="text-sm" data-testid="addon-notice">{notice}</p>{/if}
    {#if !loaded}
      <LoadingCards />
    {:else}
      <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
        {#each addons as a (a.name)}
          {@const configurations = bindings.filter((b) => b.addon === a.name)}
          <li class="space-y-3 px-4 py-4" id="addon-{a.name}" data-testid="addon-card">
            <div class="flex flex-wrap items-start gap-x-4 gap-y-3">
              <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:flex"><Puzzle class="size-4" /></span>
              <div class="min-w-0 flex-1 basis-60 space-y-1">
                <p class="flex flex-wrap items-center gap-2">
                  <span class="font-medium">{a.name}</span>
                  <span class="rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground" data-testid="addon-origin">{origin(a)}</span>
                  {#if a.image && !a.imagePresent}
                    <a
                      class="inline-flex items-center gap-1 rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn hover:bg-warn/15"
                      href={href({ view: "settings", section: "images" })}
                      title="Its image is built in Settings → Images"><TriangleAlert class="size-3" />image not built</a
                    >
                  {/if}
                  {#if a.updateAvailable}
                    <button
                      type="button"
                      class="rounded-md bg-primary/10 px-1.5 py-0.5 text-xs text-primary hover:bg-primary/15"
                      onclick={() => installer?.look(a.source ?? "")}
                      data-testid="addon-update">update available</button
                    >
                  {/if}
                </p>
                {#if a.description}<p class="text-muted-foreground">{a.description}</p>{/if}
                {#if brings(a)}<p class="fact" data-testid="addon-contents">{brings(a)}</p>{/if}
                {#if a.error}<p class="text-xs text-danger">invalid: {a.error}</p>{/if}
              </div>
              <div class="ml-auto flex shrink-0 gap-1.5">
                {#if !a.error}
                  <Button variant="outline" size="sm" onclick={() => open({ kind: "new", addon: a.name })} data-testid="new-binding">
                    <Plus />{configurations.length ? "Another configuration" : "Configure"}
                  </Button>
                {/if}
                <Button variant="ghost" size="sm" onclick={() => open({ kind: "details", addon: a.name })} data-testid="addon-details">Details</Button>
              </div>
            </div>
            {#if configurations.length}
              <ul class="divide-y overflow-hidden rounded-lg border bg-background sm:ml-13">
                {#each configurations as b (b.name)}
                  <li class="flex items-start gap-3 px-3.5 py-2.5" data-testid="binding-row">
                    <div class="min-w-0 flex-1 space-y-0.5">
                      <p class="truncate">
                        <span class="font-medium">{b.name}</span>
                        {#if b.description}<span class="text-muted-foreground"> · {b.description}</span>{/if}
                      </p>
                      {#if b.error}
                        <p class="text-xs text-danger">invalid: {b.error}</p>
                      {:else if values(b)}
                        <p class="fact truncate">{values(b)}</p>
                      {/if}
                      {#if !b.usedBy?.length}
                        <p class="text-xs text-muted-foreground" data-testid="binding-use">not used yet: give it to an agent in the agent's settings</p>
                      {/if}
                    </div>
                    {#if !b.error}
                      <Button variant="ghost" size="sm" onclick={() => open({ kind: "edit", name: b.name })} data-testid="binding-edit">Edit</Button>
                    {:else if !b.usedBy?.length}
                      <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={() => remove(b.name)} data-testid="binding-delete">Delete</Button>
                    {/if}
                  </li>
                {/each}
              </ul>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
    {#each orphans as b (b.name)}
      <p class="text-xs text-danger" data-testid="binding-row">configuration {b.name}: {b.error ?? `unknown addon ${b.addon}`}</p>
    {/each}
  </div>

  <AddonInstaller bind:this={installer} oninstalled={installed} />

  <Dialog
    bind:open={() => panel !== null, (v) => (v ? null : (panel = null))}
    title={panel?.kind === "new" ? `Configure ${panel.addon}` : panel?.kind === "edit" ? `Edit ${panel.name}` : (addon?.name ?? "")}
    description={panel?.kind === "edit"
      ? binding?.usedBy?.length
        ? `Used by ${binding.usedBy.join(", ")}.`
        : "Not used yet: give it to an agent in the agent's settings."
      : (addon?.description ?? undefined)}
    wide
    testid="addon-dialog"
  >
    {#if panel?.kind === "new" && addon}
      <BindingForm addon={addon} start={freeName(addon.name)} onsave={create} oncancel={() => (panel = null)} {error} />
    {:else if panel?.kind === "edit" && addon && binding}
      {@const b = binding}
      <BindingForm
        addon={addon}
        start={b.name}
        editing={b}
        onsave={(body) => update(b.name, body)}
        oncancel={() => (panel = null)}
        ondelete={b.usedBy?.length ? undefined : () => remove(b.name)}
        {error}
      />
    {:else if panel?.kind === "details" && addon}
      {@const a = addon}
      <div class="space-y-5">
        <dl class="space-y-3 rounded-[10px] border bg-card p-4">
          {#each [["Comes from", a.builtin ? "Handler (built-in)" : (a.source ?? "your addons folder"), true], ["Its folder", a.directory, true], ["Its agents reach", a.egress?.join(", ") || "no host", true], ["Settings", a.settings?.map((x) => x.name).join(", ") || "none", true], ["Secrets", a.secretSlots?.map((x) => x.name).join(", ") || "none", true], ["Programs", a.commands?.join(", ") || "none", true], ["Skills", a.skills?.join(", ") || "none", true], ["Image", a.image ? `${a.image}${a.imagePresent ? "" : " (not built yet)"}` : "none", true]] as [label, value] (label)}
            <div class="grid gap-1 sm:grid-cols-[8rem_1fr]">
              <dt class="text-muted-foreground">{label}</dt>
              <dd class="font-mono text-xs leading-5 break-words">{value}</dd>
            </div>
          {/each}
        </dl>
        {#if a.image && !a.imagePresent}
          <p class="text-xs text-muted-foreground">Its image is built in <a class="text-link hover:underline" href={href({ view: "settings", section: "images" })}>Settings → Images</a>.</p>
        {/if}
        {#if error}<p class="text-danger" data-testid="binding-error">{error}</p>{/if}
        <div class="flex flex-wrap items-center gap-2 border-t pt-4">
          {#if a.source}
            <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={() => removeAddon(a.name)} data-testid="addon-remove">Uninstall</Button>
            {#if !a.updateAvailable}
              <Button variant="ghost" size="sm" onclick={() => ((panel = null), installer?.look(a.source ?? ""))} data-testid="addon-update">Reinstall</Button>
            {/if}
          {:else if a.builtin}
            <span class="text-xs text-muted-foreground">Built in: it comes with Handler.</span>
          {/if}
          <span class="flex-1"></span>
          {#if a.updateAvailable}
            <Button size="sm" onclick={() => ((panel = null), installer?.look(a.source ?? ""))}>See the update</Button>
          {/if}
          <Button variant="outline" size="sm" onclick={() => (panel = null)}>Close</Button>
        </div>
      </div>
    {/if}
  </Dialog>
</section>
