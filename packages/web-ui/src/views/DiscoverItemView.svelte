<script lang="ts">
  // One thing a source offers (D.26), before anything is installed: who it comes from (Handler's,
  // reviewed; or a source you added, which Handler does not check: said in amber), its README as
  // written, what it may do and what it needs from you (from its manifest, lib/sources.ts
  // itemFacts), and its button to its kind's own install page. An item not offered says why.
  import AppWindow from "@lucide/svelte/icons/app-window";
  import Bot from "@lucide/svelte/icons/bot";
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import GitFork from "@lucide/svelte/icons/git-fork";
  import Puzzle from "@lucide/svelte/icons/puzzle";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { markdown } from "@handler/acp-view/lib/render";
  import { Button } from "$lib/components/ui/button";
  import PageHeader from "../components/PageHeader.svelte";
  import When from "../components/When.svelte";
  import { api } from "../lib/api";
  import type { SourceItemDetail } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import { actionWords, fromWords, itemFacts, takeItem, type KindPath } from "../lib/sources";

  let { source, kind, name }: { source: string; kind: KindPath; name: string } = $props();

  let detail = $state<SourceItemDetail | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);

  $effect(() => {
    api.sourceItem(source, kind, name).then(
      (d) => (detail = d),
      (e: Error) => (error = e.message),
    );
  });

  const ICON = { app: AppWindow, agents: Bot, addon: Puzzle };
  const facts = $derived(detail ? itemFacts(detail) : { mayDo: [], needs: [] });
  const item = $derived(detail?.item);
  const action = $derived(item ? actionWords(item) : null);
  const kindWords = $derived.by(() => {
    if (!detail || !item) return "";
    if (item.kind === "app") return `App · ${item.version}`;
    if (item.kind === "agents") {
      const n = detail.agents?.agents.length ?? 0;
      return `Agents for a project · ${n} ${n === 1 ? "agent" : "agents"} · version ${item.version}`;
    }
    return "Tool for agents (an addon)";
  });

  async function take(): Promise<void> {
    if (!item) return;
    busy = true;
    error = null;
    try {
      await takeItem(source, item);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<PageHeader titled title={name} parent={{ label: "Discover", href: href({ view: "discover" }) }} />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-5xl space-y-6 px-8 py-10" data-testid="discover-item-page">
    {#if error}<p class="text-sm text-danger" data-testid="discover-item-error">{error}</p>{/if}
    {#if detail && item}
      {@const Icon = ICON[item.kind]}
      <div class="flex flex-wrap items-center gap-4">
        <span class="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary"><Icon class="size-7" /></span>
        <div class="min-w-0 flex-1">
          <h1 class="text-2xl font-semibold">{item.name}</h1>
          <p class="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <span>{kindWords}</span>
            {#if detail.source.official}
              <span class="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary"><ShieldCheck class="size-3" />from Handler</span>
            {:else}
              <span class="inline-flex items-center gap-1 rounded-full border bg-muted px-2 py-0.5 text-xs"><GitFork class="size-3" />{fromWords(detail.source)}</span>
            {/if}
            {#if detail.source.commit}<span class="fact">commit {detail.source.commit.slice(0, 7)}</span>{/if}
          </p>
        </div>
        {#if item.error}
          <span class="text-sm text-muted-foreground">Not offered</span>
        {:else if action}
          <Button disabled={busy} variant={detail.source.official ? "default" : "outline"} onclick={take} data-testid="discover-item-page-take">{action}</Button>
        {:else}
          <span class="inline-flex items-center gap-1.5 text-sm text-ok" data-testid="discover-item-page-installed"><CircleCheck class="size-4" />Installed</span>
        {/if}
      </div>
      {#if item.error}
        <p class="flex items-start gap-2.5 rounded-[10px] border border-warn/40 bg-warn/5 p-3 text-sm text-warn"><TriangleAlert class="mt-0.5 size-4 shrink-0" />Not offered: {item.error}</p>
      {:else if detail.source.official}
        <p class="flex items-start gap-2.5 rounded-[10px] bg-primary/10 p-3 text-sm text-primary" data-testid="discover-item-trust">
          <ShieldCheck class="mt-0.5 size-4 shrink-0" />Reviewed by Handler's maintainer before it was offered. You still see what it may do, and choose what you give it, before anything is installed.
        </p>
      {:else}
        <p class="flex items-start gap-2.5 rounded-[10px] border border-warn/40 bg-warn/5 p-3 text-sm text-warn" data-testid="discover-item-trust">
          <TriangleAlert class="mt-0.5 size-4 shrink-0" />From a source you added: Handler does not check it. Read what it does before you install it; what it may do is shown again on its install page.
        </p>
      {/if}
      <div class="grid items-start gap-7 lg:grid-cols-[1fr_20rem]">
        <div class="min-w-0 space-y-5">
          {#if detail.readme}
            <div class="md text-sm" data-testid="discover-item-readme">{@html markdown(detail.readme)}</div>
          {:else if item.description}
            <p class="text-sm text-muted-foreground">{item.description}</p>
          {/if}
          {#if detail.agents}
            <section class="space-y-2">
              <h2 class="font-semibold">Its agents</h2>
              <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
                {#each detail.agents.agents as a (a.part)}
                  <li class="flex items-center gap-3 px-4 py-3">
                    <Bot class="size-4 text-muted-foreground" />
                    <div class="min-w-0 flex-1">
                      <p class="font-medium">{a.definition.agentName}</p>
                      <p class="fact">{a.definition.agentDescription ?? (a.definition.interface ? "a form to start" : "you talk with it")}{a.checks?.length ? ` · ${a.checks.length} checks` : ""}</p>
                    </div>
                  </li>
                {/each}
              </ul>
            </section>
          {/if}
        </div>
        <aside class="space-y-4">
          {#if facts.mayDo.length}
            <section class="rounded-[10px] border bg-card shadow-panel" data-testid="discover-item-may-do">
              <h3 class="section-label px-4 pt-3 pb-1">what it may do</h3>
              <ul class="space-y-1.5 px-4 pb-3 text-sm">
                {#each facts.mayDo as f (f.text)}
                  <li class={f.weakens ? "text-warn" : ""}>{f.text}</li>
                {/each}
              </ul>
            </section>
          {/if}
          {#if facts.needs.length}
            <section class="rounded-[10px] border bg-card shadow-panel">
              <h3 class="section-label px-4 pt-3 pb-1">what it needs from you</h3>
              <ul class="space-y-1.5 px-4 pb-3 text-sm">
                {#each facts.needs as n (n)}<li>{n}</li>{/each}
              </ul>
            </section>
          {/if}
          <section class="rounded-[10px] border bg-card text-sm shadow-panel">
            <h3 class="section-label px-4 pt-3 pb-1">about</h3>
            <dl class="space-y-1.5 px-4 pb-3">
              <div class="flex justify-between gap-3"><dt class="text-muted-foreground">source</dt><dd class="truncate" title={detail.source.url}>{detail.source.official ? "Handler" : (detail.source.name ?? detail.source.id)}</dd></div>
              <div class="flex justify-between gap-3"><dt class="text-muted-foreground">read</dt><dd><When at={detail.source.fetchedAt} /></dd></div>
              <div class="flex justify-between gap-3"><dt class="text-muted-foreground">installed</dt><dd>{item.kind === "agents" ? "agents are yours once set up" : item.installed ? "yes" : "no"}</dd></div>
            </dl>
          </section>
        </aside>
      </div>
    {:else if !error}
      <p class="fact">Reading it…</p>
    {/if}
  </div>
</div>
