<script lang="ts">
  // Providers (D.12): where a harness sends its model calls (a local llama.cpp, the Anthropic API
  // with a key…). New ones start from a template (templates/providers/) or empty, from Model access
  // (start); every one is edited in a form (ProviderForm), renamed while no agent uses it, deleted
  // anyway once confirmed (its agents then cannot start until given another provider). Shown once
  // there is one, or one being made. The list comes from Model access.
  import { productName } from "../lib/harnesses.svelte";
  import ContextTag from "./ContextTag.svelte";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { ProviderInfo, ProviderRequest, ProviderTemplate } from "../lib/contracts.gen";
  import ProviderForm from "./ProviderForm.svelte";

  let {
    providers,
    onchange,
  }: {
    providers: ProviderInfo[];
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

  const create = (body: ProviderRequest) => run(() => api.createProvider(body));
  const update = (name: string, body: ProviderRequest) => run(() => api.updateProvider(name, body));
  function remove(p: ProviderInfo): void {
    const used = p.agents?.length
      ? `\n\nUsed by ${p.agents.join(", ")}: they will not start until you give them another provider.`
      : "";
    if (confirm(`Delete the provider ${p.name} and its key?${used}`)) void run(() => api.deleteProvider(p.name));
  }
</script>

{#if providers.length || panel?.kind === "new"}
  <section class="scroll-mt-6 space-y-4" id="providers" data-testid="providers">
    <div class="space-y-1">
      <h2 class="flex items-center gap-2 text-base font-semibold">
        Providers <span class="rounded-md bg-muted px-1.5 py-0.5 text-xs font-normal text-muted-foreground">API key</span>
      </h2>
      <p class="max-w-2xl text-sm text-muted-foreground">An API and its key, or a model server on this computer: used by the agent programs each one lists.</p>
    </div>
    {#if error}<p class="text-sm text-danger" data-testid="provider-error">{error}</p>{/if}
    {#if panel?.kind === "new"}
      <ProviderForm start={panel.start} onsave={create} oncancel={() => (panel = null)} />
    {/if}
    <div class="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-3">
      {#each providers as p (p.name)}
        {#if panel?.kind === "edit" && panel.provider.name === p.name}
          <div class="col-span-full">
            <ProviderForm start={p} editing={p} onsave={(body) => update(p.name, body)} oncancel={() => (panel = null)} />
          </div>
        {:else}
          <div class="flex flex-col gap-2 rounded-lg border bg-card p-3.5 text-sm" data-testid="provider-card">
            <div class="min-w-0">
              <div class="truncate font-medium">{p.name}</div>
              {#if p.description}<div class="truncate text-xs text-muted-foreground">{p.description}</div>{/if}
            </div>
            {#if p.contexts?.length}<div class="flex flex-wrap gap-1">{#each p.contexts as c (c)}<ContextTag name={c} />{/each}</div>{/if}
            <p class="text-xs {p.status === 'ready' ? 'text-ok' : p.status === 'incomplete' ? 'text-warn' : 'text-danger'}" data-testid="provider-status">
              {p.status === "ready" ? "● ready" : p.status === "incomplete" ? "● to finish" : "● invalid"}
            </p>
            {#if p.error}<p class="text-xs whitespace-normal text-danger">{p.error}</p>{/if}
            {#each p.problems ?? [] as problem (problem)}<p class="text-xs whitespace-normal text-warn">{problem}</p>{/each}
            <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
              {#if p.models?.length}
                <dt class="text-muted-foreground">models</dt>
                <dd class="truncate font-mono" title={p.models.map((m) => m.id).join(", ")}>{p.models.map((m) => m.id).join(", ")}</dd>
              {/if}
              {#if p.harnesses?.length}<dt class="text-muted-foreground">for</dt><dd class="truncate">{p.harnesses.map((h) => productName(h)).join(", ")}</dd>{/if}
              <dt class="text-muted-foreground">agents</dt>
              <dd class="truncate">{p.agents?.length ? p.agents.join(", ") : "none"}</dd>
              {#if p.files?.length}<dt class="text-muted-foreground">files for</dt><dd class="truncate font-mono">{p.files.join(", ")}</dd>{/if}
            </dl>
            {#if p.status !== "invalid"}
              <div class="flex gap-1">
                <Button variant="outline" size="sm" onclick={() => (panel = { kind: "edit", provider: p })} data-testid="provider-edit">Edit</Button>
                <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={() => remove(p)} data-testid="provider-delete">Delete</Button>
              </div>
            {/if}
          </div>
        {/if}
      {/each}
    </div>
  </section>
{/if}
