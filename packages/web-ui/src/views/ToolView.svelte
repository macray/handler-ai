<script lang="ts">
  // A tool's page (#/library/tools/:name; G, D.15): the tool first (what it is, the sites it
  // reaches, its state; a broken one's message in full), then your connections to it (a binding:
  // its settings and sealed secrets, who it is used by; Connect another, Edit in a dialog with
  // BindingForm; Delete there while nothing uses it), or "nothing to connect" for a tool with no
  // setting, then what uses it (D.22) and the facts of what it brings; just installed
  // (`connect`), its first connection's form opens. Its ⋯: its update,
  // installing it again, uninstalling it (no connection may use it).
  import Ellipsis from "@lucide/svelte/icons/ellipsis";
  import Link from "@lucide/svelte/icons/link";
  import Lock from "@lucide/svelte/icons/lock";
  import Plus from "@lucide/svelte/icons/plus";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import Trash from "@lucide/svelte/icons/trash-2";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Wrench from "@lucide/svelte/icons/wrench";
  import { Button } from "$lib/components/ui/button";
  import AddonInstaller from "../components/AddonInstaller.svelte";
  import BindingForm from "../components/BindingForm.svelte";
  import Dialog from "../components/Dialog.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import Popover from "../components/Popover.svelte";
  import UsesPanel from "../components/UsesPanel.svelte";
  import { api } from "../lib/api";
  import type { AddonInfo, BindingInfo, BindingRequest } from "../lib/contracts.gen";
  import { href, navigate } from "../lib/router.svelte";
  import { hasSlots } from "../lib/setup";
  import { brokenBecause, sitesWords, TOOL_STATE, toolOrigin, toolState } from "../lib/tools";
  import { freeName } from "../lib/text";

  let { name, connect: connectFirst = false }: { name: string; connect?: boolean } = $props();

  type Panel = { kind: "new" } | { kind: "edit"; name: string };
  let tool = $state<AddonInfo | null>(null);
  let connections = $state<BindingInfo[]>([]);
  let loaded = $state(false);
  let error = $state<string | null>(null);
  let panel = $state<Panel | null>(null);
  let menuOpen = $state(false);
  let installer = $state<AddonInstaller | null>(null);
  let opened = false; // its first connection's form, opened once (`connect`)

  async function load(): Promise<void> {
    try {
      const [all, bindings] = await Promise.all([api.addons(), api.bindings()]);
      tool = all.find((t) => t.name === name) ?? null;
      connections = bindings.filter((b) => b.addon === name);
      if (!tool) error = `No tool named ${name} is installed.`;
      else if (connectFirst && !opened && hasSlots(tool) && !connections.length) {
        opened = true; // once: the form of its first connection, just installed
        void connect();
      }
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loaded = true;
    }
  }

  $effect(() => {
    void load();
  });

  const editing = $derived.by(() => {
    const p = panel;
    return p?.kind === "edit" ? connections.find((c) => c.name === p.name) : undefined;
  });
  const status = $derived(tool ? toolState(tool, connections) : null);
  const used = $derived(connections.some((c) => c.usedBy?.length));

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

  /** `base`, or `base-2`, `base-3`… when a connection has it. */
  async function connectionName(base: string): Promise<string> {
    return freeName(base, (await api.bindings().catch(() => connections)).map((b) => b.name));
  }
  let fresh = $state("");
  async function connect(): Promise<void> {
    fresh = await connectionName(name);
    error = null;
    panel = { kind: "new" };
  }

  const create = (body: BindingRequest) => run(() => api.createBinding(body));
  const update = (n: string, body: BindingRequest) => run(() => api.updateBinding(n, body));
  const remove = (n: string) => confirm(`Delete the connection ${n} and its secrets?`) && run(() => api.deleteBinding(n));

  async function uninstall(): Promise<void> {
    if (!confirm(`Uninstall ${name}? Its folder and its image go; no connection may use it.`)) return;
    try {
      await api.removeAddon(name);
      navigate({ view: "library", shelf: "tools" }, true);
    } catch (e) {
      error = (e as Error).message;
    }
  }

  const values = (b: BindingInfo) => Object.entries(b.settings ?? {}).map(([k, v]) => `${k}=${v}`).join("  ");
  const TONE = { broken: "text-warn", "not-set-up": "text-warn", "not-ready": "text-warn", preparing: "text-muted-foreground", ready: "text-ok" } as const;
</script>

<PageHeader width="max-w-4xl" title={name} parent={{ label: "Library › Tools", href: href({ view: "library", shelf: "tools" }) }}>
  {#snippet menu()}
    {#if tool?.source || tool?.updateAvailable}
      <Popover bind:open={menuOpen} align="end" label="More" width="15rem" testid="tool-menu">
        {#snippet trigger(props)}
          <Button variant="ghost" size="icon" class="size-8 text-muted-foreground" {...props} aria-label="More" data-testid="tool-more"><Ellipsis /></Button>
        {/snippet}
        {#snippet children(close)}
          {#if tool?.source}
            <button type="button" class="menu-item" onclick={() => (void installer?.look(tool?.source ?? ""), close())} data-testid="addon-update"
              ><RefreshCw />{tool.updateAvailable ? "See the update" : "Install it again"}</button
            >
            <button type="button" class="menu-item text-danger" onclick={() => (close(), void uninstall())} data-testid="addon-remove"><Trash />Uninstall</button>
          {/if}
        {/snippet}
      </Popover>
    {/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-8 px-8 py-6" data-testid="tool-page">
    {#if error && !panel}<p class="text-sm text-danger" data-testid="binding-error">{error}</p>{/if}
    {#if !loaded}
      <p class="text-sm text-muted-foreground">Loading…</p>
    {:else if tool && status}
      {@const t = tool}
      <section class="overflow-hidden rounded-[10px] border bg-card shadow-panel">
        <div class="flex items-start gap-3 px-4 py-4">
          <span class="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Wrench class="size-5" /></span>
          <div class="min-w-0 flex-1">
            <p class="text-sm text-muted-foreground">{t.description ?? toolOrigin(t)} · <span title={t.egress?.join(", ")}>reaches {sitesWords(t)}</span></p>
          </div>
          <span class="inline-flex items-center gap-1.5 text-xs {TONE[status]}" data-testid="tool-state">
            {#if status === "broken"}<TriangleAlert class="size-3" />{:else}<span class="size-1.5 rounded-full bg-current"></span>{/if}{TOOL_STATE[status]}
          </span>
        </div>
        {#if status === "broken"}
          <ul class="mx-4 mb-4 space-y-1 rounded-lg bg-warn/10 px-3 py-2.5 font-mono text-xs leading-5 break-words text-warn" data-testid="tool-broken">
            {#each brokenBecause(t, connections) as m (m)}<li>{m}</li>{/each}
          </ul>
        {:else if status === "not-ready" || status === "preparing"}
          <p class="mx-4 mb-4 text-xs text-muted-foreground" data-testid="addon-state-detail">
            {t.stateDetail ?? "Its programs are being prepared on this computer."} <a class="text-link hover:underline" href={href({ view: "settings", section: "sandboxes" })}>Settings → Sandboxes</a>
          </p>
        {/if}

        {#if hasSlots(t) && !t.error}
          <div class="flex items-center justify-between gap-3 border-t px-4 py-2.5">
            <h2 class="text-sm font-medium text-muted-foreground">Your connections</h2>
            <Button size="sm" variant={connections.length ? "outline" : "default"} onclick={connect} data-testid="new-binding"
              ><Plus />{connections.length ? "Connect another" : "Connect"}</Button
            >
          </div>
          {#if connections.length}
            <ul class="divide-y border-t text-sm">
              {#each connections as c (c.name)}
                <li class="flex items-center gap-3 px-4 py-3" data-testid="binding-row">
                  <Link class="size-4 shrink-0 text-muted-foreground" />
                  <div class="min-w-0 flex-1 space-y-0.5">
                    <p class="truncate"><span class="font-mono font-medium">{c.name}</span>{#if c.description}<span class="text-muted-foreground"> · {c.description}</span>{/if}</p>
                    {#if c.error}
                      <p class="text-xs text-warn">Broken: {c.error}</p>
                    {:else}
                      <p class="text-xs text-muted-foreground" data-testid="binding-use">{c.usedBy?.length ? `used by ${c.usedBy.join(", ")}` : "not used yet: give it to an agent in its settings"}</p>
                      {#if values(c)}<p class="fact truncate">{values(c)}</p>{/if}
                    {/if}
                  </div>
                  {#if c.secrets?.length}<span class="inline-flex items-center gap-1 text-xs text-ok" title="Its secrets are in Handler's secret store, never shown again"><Lock class="size-3" />sealed</span>{/if}
                  <Button variant="ghost" size="sm" onclick={() => ((error = null), (panel = { kind: "edit", name: c.name }))} data-testid="binding-edit">Edit</Button>
                </li>
              {/each}
            </ul>
          {/if}
        {:else if !t.error}
          <p class="border-t px-4 py-3 text-sm text-muted-foreground" data-testid="addon-no-settings">Nothing to connect: give it to an agent, or a project, in its settings.</p>
        {/if}
      </section>

      <UsesPanel kind="addon" id={t.name} />

      <section class="space-y-2">
        <h2 class="text-sm font-medium text-muted-foreground">What it brings</h2>
        <dl class="space-y-2.5 rounded-[10px] border bg-card p-4 text-sm">
          {#each [["Comes from", t.builtin ? "Handler (built in)" : (t.source ?? "your tools folder")], ["Its folder", t.directory], ["The sites it reaches", t.egress?.join(", ") || "none"], ["Programs", t.commands?.join(", ") || "none"], ["Skills", t.skills?.join(", ") || "none"], ["Settings", t.settings?.map((x) => x.name).join(", ") || "none"], ["Secrets", t.secretSlots?.map((x) => x.name).join(", ") || "none"], ["Image", t.image ? `${t.image}${t.imagePresent ? "" : " (not built yet)"}` : "none"], ["Needs from the toolbox", t.needs?.join(", ") || "nothing more"]] as [label, value] (label)}
            <div class="grid gap-1 sm:grid-cols-[11rem_1fr]">
              <dt class="text-muted-foreground">{label}</dt>
              <dd class="font-mono text-xs leading-5 break-words">{value}</dd>
            </div>
          {/each}
        </dl>
        {#if used}<p class="text-xs text-muted-foreground">Uninstalling it waits until no agent uses its connections.</p>{/if}
      </section>
    {/if}
  </div>
</div>

<AddonInstaller bind:this={installer} oninstalled={() => void load()} />

<Dialog
  bind:open={() => panel !== null, (v) => (v ? null : (panel = null))}
  title={panel?.kind === "new" ? `Connect ${name}` : panel?.kind === "edit" ? `Edit ${panel.name}` : ""}
  description={panel?.kind === "edit" ? (editing?.usedBy?.length ? `Used by ${editing.usedBy.join(", ")}.` : "Not used yet: give it to an agent in its settings.") : (tool?.description ?? undefined)}
  wide
  testid="addon-dialog"
>
  {#if panel?.kind === "new" && tool}
    <BindingForm addon={tool} start={fresh} onsave={create} oncancel={() => (panel = null)} {error} />
  {:else if panel?.kind === "edit" && tool && editing}
    {@const b = editing}
    <BindingForm addon={tool} start={b.name} editing={b} onsave={(body) => update(b.name, body)} oncancel={() => (panel = null)} ondelete={b.usedBy?.length ? undefined : () => remove(b.name)} {error} />
  {/if}
</Dialog>
