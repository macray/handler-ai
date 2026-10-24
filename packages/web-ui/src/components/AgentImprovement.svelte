<script lang="ts">
  // A job's last improvement (D.21), under its checks: the goal, how far it got (attempt n of
  // max, or why it ended), each attempt (the prompt writer's line, its checks as dots, the best
  // one marked, its instructions unfolded), Stop while it runs, Keep an attempt once it ended (an
  // ordinary save of the agent's instructions; attempt 0 puts them back). Polled while it runs.
  import Sparkles from "@lucide/svelte/icons/sparkles";
  import { Button } from "$lib/components/ui/button";
  import { api } from "../lib/api";
  import type { Agent, Improvement } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";

  let { agent, onkept }: { agent: Agent; onkept?: () => void } = $props();

  let last = $state<Improvement | null>(null);
  let error = $state<string | null>(null);
  const running = $derived(last?.state === "running");
  const total = $derived(last?.attempts[0]?.results?.length ?? 0);
  // what the agent has now: the attempt kept, else the one it started from
  const current = $derived(last ? (last.kept ?? 0) : 0);

  async function load(): Promise<void> {
    try {
      last = (await api.improvements(agent.id))[0] ?? null;
    } catch (e) {
      error = (e as Error).message;
    }
  }
  $effect(() => {
    void agent.id;
    void load();
  });
  $effect(() => {
    if (!running) return;
    const timer = setInterval(load, 1000);
    return () => clearInterval(timer);
  });

  async function stop(): Promise<void> {
    if (last) last = await api.stopImprovement(agent.id, last.id);
  }

  async function keep(n: number): Promise<void> {
    if (!last) return;
    error = null;
    try {
      last = await api.keepAttempt(agent.id, last.id, n);
      onkept?.();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  const DOT = { passed: "bg-ok", failed: "bg-danger/60", error: "bg-warn", running: "bg-muted-foreground/40 animate-pulse", waiting: "bg-border" };
</script>

{#if last}
  <section class="overflow-hidden rounded-[10px] border bg-card shadow-panel" data-testid="agent-improvement">
    <header class="flex flex-wrap items-center gap-2 border-b px-3.5 py-2.5">
      <h3 class="flex items-center gap-2 text-sm font-semibold"><Sparkles class="size-4 text-muted-foreground" />{running ? "Improving" : "Last improvement"}</h3>
      <span class="text-xs text-muted-foreground" data-testid="improvement-state">
        {#if running}attempt {last.attempts.length - 1} of {last.maxAttempts}{:else}{last.why ?? last.state}{/if}
      </span>
      {#if running}<Button size="sm" variant="ghost" class="ml-auto" onclick={stop} data-testid="improvement-stop">Stop</Button>{/if}
    </header>
    <p class="border-b px-3.5 py-2 text-xs text-muted-foreground">Goal: <span class="text-foreground">{last.goal}</span></p>
    <ul class="divide-y">
      {#each last.attempts as a (a.n)}
        <li class="space-y-1 px-3.5 py-2.5 text-sm {a.n === last.best && a.n > 0 ? 'bg-accent-soft/40' : ''}" data-testid="attempt-row">
          <div class="flex flex-wrap items-center gap-2">
            <span class="fact w-5 text-muted-foreground">{a.n}</span>
            <span class="min-w-0 flex-1 truncate">{a.n === 0 ? "The instructions it started from" : (a.change ?? (a.state === "writing" ? "Writing…" : (a.why ?? "")))}</span>
            <span class="flex gap-0.5" aria-label="its checks">
              {#each a.results as r (r.checkId)}<span class="size-3 rounded-sm {DOT[r.state]}" title="{r.name}: {r.state}{r.why ? ` (${r.why})` : ''}"></span>{/each}
            </span>
            <span class="fact w-14 text-right text-xs {a.state === 'done' && a.passed === total ? 'text-ok' : 'text-muted-foreground'}">
              {a.state === "done" ? `${a.passed} of ${total}` : a.state === "error" ? "no try" : "…"}
            </span>
            {#if a.n === last.best && a.n > 0}<span class="rounded bg-accent-soft px-1.5 text-xs text-accent-soft-foreground">best</span>{/if}
            {#if a.n === current && last.kept !== null && last.kept !== undefined}<span class="rounded bg-muted px-1.5 text-xs" data-testid="attempt-kept">kept</span>{/if}
            {#if !running && a.state === "done" && a.n !== current}
              <Button size="sm" variant={a.n === last.best ? "default" : "ghost"} onclick={() => keep(a.n)} data-testid="attempt-keep">{a.n === 0 ? "Back to these" : "Keep"}</Button>
            {/if}
          </div>
          {#if a.instructions}
            <details class="pl-7 text-xs">
              <summary class="cursor-pointer text-muted-foreground">Its instructions{#if a.writerRun}{" · "}<a class="text-link hover:underline" href={href({ view: "run", id: a.writerRun })}>the writer's run</a>{/if}</summary>
              <pre class="mt-1 rounded-md bg-muted p-2 font-sans whitespace-pre-wrap">{a.instructions}</pre>
            </details>
          {/if}
          {#if a.state === "error" && a.why}<p class="pl-7 text-xs text-warn">{a.why}</p>{/if}
        </li>
      {/each}
    </ul>
    {#if error}<p class="border-t px-3.5 py-2 text-xs text-danger">{error}</p>{/if}
    <p class="border-t px-3.5 py-2 text-xs text-muted-foreground">Nothing changes in the agent until you keep an attempt; its checks judge each one.</p>
  </section>
{/if}
