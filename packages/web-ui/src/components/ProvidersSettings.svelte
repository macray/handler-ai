<script lang="ts">
  // Providers (D.12): where a harness sends its model calls (a local llama.cpp, the Anthropic API
  // with a key…). New ones start from a template (templates/providers/) or empty, from Model access
  // (start); every one is edited in a form (ProviderForm) in a dialog, renamed while no agent uses
  // it, deleted anyway once confirmed (its agents then cannot start until given another provider).
  // Listed once there is one. The list comes from Model access.
  import { productName } from "../lib/harnesses.svelte";
  import AreaTag from "./AreaTag.svelte";
  import KeyRound from "@lucide/svelte/icons/key-round";
  import Plus from "@lucide/svelte/icons/plus";
  import Dialog from "./Dialog.svelte";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { ProviderInfo, ProviderRequest, ProviderTemplate } from "../lib/contracts.gen";
  import ProviderForm from "./ProviderForm.svelte";

  let {
    providers,
    listed,
    onadd,
    onchange,
  }: {
    providers: ProviderInfo[];
    listed: boolean; // the section shown, even empty (once there is an account or a provider)
    onadd: () => void; // its Add: Model access's picker of APIs
    onchange: () => Promise<void>; // reloads `providers`
  } = $props();

  // the panel open: a new provider's form, or a provider's
  type Panel = { kind: "new"; start: ProviderTemplate } | { kind: "edit"; provider: ProviderInfo };
  let panel = $state<Panel | null>(null);
  let error = $state<string | null>(null);

  const EMPTY: ProviderTemplate = { name: "", endpoints: {}, models: [{ id: "" }] };

  async function run(action: () => Promise<unknown>): Promise<void> {
    error = null;
    try {
      await action();
      panel = null;
      await onchange();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  /** A new provider from this template, or empty (null). */
  export function start(template: ProviderTemplate | null): void {
    error = null;
    panel = { kind: "new", start: template ? { ...template, name: freeName(template.name) } : EMPTY };
  }

  /** A template's name, or `name-2`, `name-3`… when a provider has it. */
  function freeName(base: string): string {
    let name = base;
    for (let i = 2; providers.some((p) => p.name === name); i++) name = `${base}-${i}`;
    return name;
  }

  /** Who can use it, in one line: its models, the programs speaking it, the config files it gives. */
  const reach = (p: ProviderInfo) =>
    [
      p.models?.map((m) => m.id).join(", "),
      p.harnesses?.length ? `for ${p.harnesses.map((h) => productName(h)).join(", ")}` : null,
      p.files?.length ? `files for ${p.files.join(", ")}` : null,
    ]
      .filter(Boolean)
      .join(" · ");
  /** What uses it, said in its Edit (and before it is deleted), not on its line. */
  const use = (p: ProviderInfo) => (p.agents?.length ? `Used by ${p.agents.join(", ")}.` : "No agent uses it.");

  const create = (body: ProviderRequest) => run(() => api.createProvider(body));
  const update = (name: string, body: ProviderRequest) => run(() => api.updateProvider(name, body));
  function remove(p: ProviderInfo): void {
    const used = p.agents?.length
      ? `\n\nUsed by ${p.agents.join(", ")}: they will not start until you give them another provider.`
      : "";
    if (confirm(`Delete the provider ${p.name} and its key?${used}`)) void run(() => api.deleteProvider(p.name));
  }
</script>

{#if providers.length || listed}
  <section class="enter space-y-4" id="providers" data-testid="providers">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div class="space-y-1">
        <h2 class="flex items-center gap-2 text-base font-semibold">
          Providers <span class="rounded-md bg-muted px-1.5 py-0.5 text-xs font-normal text-muted-foreground">API key</span>
        </h2>
        <p class="max-w-2xl text-sm text-muted-foreground">An API and its key, or a model server on this computer: used by the agent programs each one lists.</p>
      </div>
      <Button variant="outline" size="sm" onclick={onadd} data-testid="add-provider"><Plus />Add a provider</Button>
    </div>
    {#if error && !panel}<p class="text-sm text-danger" data-testid="provider-error">{error}</p>{/if}
    {#if providers.length}
    <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
      {#each providers as p (p.name)}
        <li class="flex flex-wrap items-start gap-x-4 gap-y-3 px-4 py-4" data-testid="provider-card">
          <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:flex"><KeyRound class="size-4" /></span>
          <div class="min-w-0 flex-1 basis-60 space-y-1">
            <p class="flex flex-wrap items-center gap-2">
              <span class="truncate font-medium">{p.name}</span>
              {#if p.description}<span class="truncate text-xs text-muted-foreground">{p.description}</span>{/if}
              {#each p.areas ?? [] as c (c)}<AreaTag name={c} />{/each}
            </p>
            <p class="text-xs {p.status === 'ready' ? 'text-ok' : p.status === 'incomplete' ? 'text-warn' : 'text-danger'}" data-testid="provider-status">
              {p.status === "ready" ? "● ready" : p.status === "incomplete" ? "● to finish" : "● invalid"}
            </p>
            {#if p.error}<p class="text-xs whitespace-normal text-danger">{p.error}</p>{/if}
            {#each p.problems ?? [] as problem (problem)}<p class="text-xs whitespace-normal text-warn">{problem}</p>{/each}
<p class="fact truncate" title={reach(p)}>{reach(p)}</p>
          </div>
          {#if p.status !== "invalid"}
            <Button variant="ghost" size="sm" class="ml-auto" onclick={() => (error = null, panel = { kind: "edit", provider: p })} data-testid="provider-edit">Edit</Button>
          {/if}
        </li>
      {/each}
    </ul>
    {:else}
      <p class="rounded-[10px] border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">No provider yet. An API key, or a model running on this computer.</p>
    {/if}
  </section>
{/if}

<Dialog
  bind:open={() => panel !== null, (v) => (v ? null : (panel = null))}
  title={panel?.kind === "edit" ? `Edit ${panel.provider.name}` : "New provider"}
  description={panel?.kind === "new" ? "An API and its key, or a model server on this computer." : panel?.kind === "edit" ? use(panel.provider) : undefined}
  wide
  testid="provider-dialog"
>
  {#if panel?.kind === "new"}
    <ProviderForm start={panel.start} onsave={create} oncancel={() => (panel = null)} {error} />
  {:else if panel?.kind === "edit"}
    {@const p = panel.provider}
    <ProviderForm start={p} editing={p} onsave={(body) => update(p.name, body)} oncancel={() => (panel = null)} ondelete={() => remove(p)} {error} />
  {/if}
</Dialog>
