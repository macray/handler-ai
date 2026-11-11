<script lang="ts">
  // Providers (D.12): where a harness sends its model calls (a local llama.cpp, the Anthropic API
  // with a key…). New ones start from a template (templates/providers/) or empty, from Model access
  // (start); every one is edited in a form (ProviderForm) in a dialog, renamed while no agent uses
  // it, deleted anyway once confirmed (its agents then cannot start until given another provider).
  // Listed by name once there is one, as "API keys and local models": a line is its description
  // and model count after a dot, its state said unless ready; a provider that cannot be read is
  // deleted from its line. The list comes from Model access.
  import { productName } from "../lib/harnesses.svelte";
  import AreaTag from "./AreaTag.svelte";
  import Dialog from "./Dialog.svelte";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { ProviderInfo, ProviderRequest, ProviderTemplate } from "../lib/contracts.gen";
  import ProviderForm from "./ProviderForm.svelte";
  import { statusOf } from "../lib/providers";
  import { freeName } from "../lib/text";

  let {
    providers,
    listed,
    onchange,
  }: {
    providers: ProviderInfo[];
    listed: boolean; // the section shown, even empty (once there is an account or a provider)
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
    panel = { kind: "new", start: template ? { ...template, name: freeName(template.name, providers.map((p) => p.name)) } : EMPTY };
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
  /** How many models it serves, in a word ("3 models"); their names on hover and in its Edit. */
  const models = (p: ProviderInfo) => (p.models?.length ? `${p.models.length} model${p.models.length === 1 ? "" : "s"}` : null);
  /** What uses it, said in its Edit (and before it is deleted), not on its line. */
  const use = (p: ProviderInfo) => (p.agents?.length ? `Used by ${p.agents.join(", ")}.` : "No agent uses it.");

  // a server on this computer, tested from its line: ready once it answers
  let testing = $state<string | null>(null);
  async function test(p: ProviderInfo): Promise<void> {
    testing = p.name;
    error = null;
    try {
      await api.testProvider({ provider: p.name });
      await onchange();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      testing = null;
    }
  }

  const sorted = $derived([...providers].sort((a, b) => a.name.localeCompare(b.name)));

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
  <section class="enter space-y-3" id="providers" data-testid="providers">
    <h2 class="flex flex-wrap items-baseline gap-x-2 text-base font-semibold">
      API keys and local models
      {#if providers.length}<span class="font-mono text-xs font-normal text-muted-foreground">{providers.length}</span>{/if}
      <span class="text-xs font-normal text-muted-foreground">· pay per use, or free on this computer; recommended for automations</span>
    </h2>
    {#if error && !panel}<p class="text-sm text-danger" data-testid="provider-error">{error}</p>{/if}
    {#if providers.length}
    <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
      {#each sorted as p (p.name)}
        {@const shown = statusOf(p)}
        <li class="flex items-center gap-x-4 px-4 py-3" data-testid="provider-card">
          <span class="hidden size-8 shrink-0 items-center justify-center rounded-lg border bg-muted/50 text-xs font-semibold text-muted-foreground sm:flex" aria-hidden="true"
            >{(p.description ?? p.name).charAt(0).toUpperCase()}</span
          >
          <div class="min-w-0 flex-1 space-y-0.5">
            <p class="flex flex-wrap items-center gap-2">
              <span class="truncate font-medium">{p.name}</span>
              {#each p.areas ?? [] as c (c)}<AreaTag name={c} />{/each}
            </p>
            <!-- ready: the dot alone; its models, programs and files on hover and in Edit -->
            <p class="truncate text-xs text-muted-foreground" title={reach(p)}>
              <span class={shown.state === "ready" ? "text-ok" : shown.state === "warn" ? "text-warn" : "text-danger"} data-testid="provider-status"
                >●{#if shown.state === "ready"}<span class="sr-only">{" "}{shown.text}</span>{:else}{" "}{shown.text}{/if}</span
              >
              <span>{shown.state === "ready" ? " " : " · "}{[p.description, models(p)].filter(Boolean).join(" · ")}</span>
            </p>
            {#if p.status === "ready" && p.local && p.reached && !p.reached.ok}<p class="text-xs whitespace-normal text-danger" data-testid="provider-not-reached">{p.reached.error}</p>{/if}
            {#if p.error}<p class="text-xs whitespace-normal text-danger">{p.error}</p>{/if}
            {#each p.problems ?? [] as problem (problem)}<p class="text-xs whitespace-normal text-warn">{problem}</p>{/each}
          </div>
          {#if p.status === "ready" && p.local}
            <Button variant="outline" size="sm" class="ml-auto" disabled={testing === p.name} onclick={() => void test(p)} data-testid="provider-card-test">{testing === p.name ? "Testing…" : "Test"}</Button>
          {/if}
          {#if p.status === "invalid"}
            <Button variant="outline" size="sm" class="ml-auto" onclick={() => remove(p)} data-testid="provider-delete-row">Delete…</Button>
          {:else}
            <Button variant="ghost" size="sm" class={p.status === "ready" && p.local ? "" : "ml-auto"} onclick={() => (error = null, panel = { kind: "edit", provider: p })} data-testid="provider-edit">Edit</Button>
          {/if}
        </li>
      {/each}
    </ul>
    {:else}
      <p class="rounded-[10px] border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">None yet. An API key, or a model running on this computer.</p>
    {/if}
  </section>
{/if}

<Dialog
  bind:open={() => panel !== null, (v) => (v ? null : (panel = null))}
  title={panel?.kind === "edit" ? `Edit ${panel.provider.name}` : "Connect an API key or a local model"}
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
