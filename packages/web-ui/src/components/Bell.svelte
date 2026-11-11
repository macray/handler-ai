<script lang="ts">
  // The bell: "need you" for every project and app, from every page, never interrupting. Quiet,
  // running (a green dot), or waiting (solid amber with the count: the only solid amber of the
  // interface). Its list: what waits first (a question answered in place when this tab is
  // attached to its session, else opened), then what runs; the Inbox at its foot.
  import BellIcon from "@lucide/svelte/icons/bell";
  import { Button } from "$lib/components/ui/button";
  import type { InboxMessage } from "../lib/contracts.gen";
  import { bell, question } from "../lib/bell.svelte";
  import { inbox } from "../lib/inbox.svelte";
  import { agentLabel, projects } from "../lib/projects.svelte";
  import { href } from "../lib/router.svelte";
  import type { LiveSession } from "../lib/sessions.svelte";

  let open = $state(false);
  let button = $state<HTMLButtonElement | null>(null);
  let list = $state<HTMLElement | null>(null);
  let at = $state({ top: 0, left: 0 });

  const waiting = $derived(bell.waiting);
  const running = $derived(bell.running);
  const told = $derived(bell.told);
  const count = $derived(bell.count);
  const look = $derived(bell.state);

  function toggle(): void {
    open = !open;
    if (open && button) {
      const r = button.getBoundingClientRect();
      at = { top: r.bottom + 6, left: r.left };
    }
  }

  /** The list on the page's top layer: the menu is a stacking context of its own, which the page
   *  would cover. */
  function onTop(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  function outside(e: PointerEvent): void {
    if (open && !list?.contains(e.target as Node) && !button?.contains(e.target as Node)) open = false;
  }

  /** Who and where: the agent's name, then its project or that it is Chat's or an app's. */
  function who(s: LiveSession): { name: string; place: string } {
    const found = projects.of(s.agent);
    if (found) return { name: agentLabel(found.agent), place: found.project.name };
    return { name: projects.label(s.agent), place: s.agent.chat ? "Chat" : (s.agent.app ?? "") };
  }

  function where(m: InboxMessage): string {
    return [m.source === "session" ? null : m.source, m.name].filter(Boolean).join(" · ");
  }
</script>

<svelte:window onpointerdown={outside} onkeydown={(e) => e.key === "Escape" && (open = false)} />

<button
  bind:this={button}
  type="button"
  class="bell {look}"
  class:open
  onclick={toggle}
  aria-expanded={open}
  aria-label={count ? `${count} need you` : running.length ? `${running.length} running` : "Nothing needs you"}
  title={count ? `${count} need you` : running.length ? `${running.length} running` : "Nothing needs you"}
  data-testid="bell"
  data-state={look}
>
  <BellIcon class="size-4" />
  {#if count}<span class="tabular-nums" data-testid="bell-count">{count}</span>{/if}
  {#if look === "running"}<span class="run"></span>{/if}
</button>

{#if open}
  <div bind:this={list} use:onTop class="list" style="top:{at.top}px;left:{at.left}px" role="dialog" aria-label="Need you" data-testid="bell-list">
    {#if count}
      <p class="group">Waiting for you</p>
      {#each waiting as s (s.key)}
        {@const q = question(s)}
        {@const w = who(s)}
        <div class="item" data-testid="bell-waiting">
          <span class="dot bg-warn"></span>
          <a class="what" href={href({ view: "session", key: s.key })} title={s.info.scope} onclick={() => (open = false)}>
            <span><b>{w.name}</b> {q ? `asks: ${q.title}` : "needs you"}</span>
            <span class="where">{[w.place, s.title].filter(Boolean).join(" · ")}</span>
          </a>
          {#if q?.allow}
            <Button size="sm" onclick={() => q.answer({ outcome: "selected", optionId: q.allow!.optionId })} data-testid="bell-allow">Allow</Button>
            {#if q.reject}<Button size="sm" variant="outline" onclick={() => q.answer({ outcome: "selected", optionId: q.reject!.optionId })} data-testid="bell-reject">No</Button>{/if}
          {:else}
            <Button size="sm" variant="outline" href={href({ view: "session", key: s.key })} onclick={() => (open = false)}>Open</Button>
          {/if}
        </div>
      {/each}
      {#each told as m (m.id)}
        <div class="item" data-testid="bell-told">
          <span class="dot {m.status === 'failed' ? 'bg-danger' : 'bg-warn'}"></span>
          <a class="what" href={href({ view: "inbox" })} onclick={() => (open = false)}>
            <span>{m.title}</span>
            <span class="where">{where(m)}</span>
          </a>
          <Button size="sm" variant="outline" href={href({ view: "inbox" })} onclick={() => (open = false)}>Open</Button>
        </div>
      {/each}
    {/if}
    {#if running.length}
      {#if count}<div class="sep"></div>{/if}
      <p class="group">Running</p>
      {#each running as s (s.key)}
        {@const w = who(s)}
        <a class="item what-row" href={href({ view: "session", key: s.key })} title={s.info.scope} onclick={() => (open = false)} data-testid="bell-running">
          <span class="dot bg-ok"></span>
          <span class="what">
            <span><b>{w.name}</b>{#if s.title} · {s.title}{/if}</span>
            {#if w.place}<span class="where">{w.place}</span>{/if}
          </span>
        </a>
      {/each}
    {/if}
    {#if !count && !running.length}
      <p class="quiet">Nothing needs you, nothing runs.</p>
    {/if}
    <div class="sep"></div>
    <a class="foot" href={href({ view: "inbox" })} onclick={() => (open = false)} data-testid="bell-inbox"
      >Inbox{#if inbox.unread}<span class="tabular-nums text-muted-foreground">{inbox.unread} unread</span>{/if}</a
    >
  </div>
{/if}

<style>
  .bell {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: 28px;
    margin-left: auto;
    padding: 0 8px;
    border-radius: 8px;
    color: var(--muted-foreground);
    font-size: 12px;
    font-weight: 650;
  }
  .bell:hover {
    background: var(--sidebar-accent);
  }
  /* waiting: the only solid amber of the interface */
  .bell.waiting {
    background: var(--warn);
    color: var(--background);
  }
  .bell.open {
    box-shadow: 0 0 0 2px color-mix(in oklab, var(--warn) 35%, transparent);
  }
  .run {
    position: absolute;
    top: 4px;
    right: 5px;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--ok);
    box-shadow: 0 0 0 2px var(--sidebar);
  }
  .list {
    position: fixed;
    z-index: 50;
    width: min(380px, calc(100vw - 16px));
    max-height: 70vh;
    overflow-y: auto;
    padding: 8px;
    border-radius: 12px;
    background: var(--popover);
    color: var(--popover-foreground);
    box-shadow: var(--float-shadow);
    font-size: 13px;
  }
  .group {
    padding: 8px 10px 4px;
    color: var(--muted-foreground);
    font-size: 11.5px;
    font-weight: 600;
  }
  .item {
    display: flex;
    align-items: center;
    gap: 9px;
    min-height: 32px;
    padding: 6px 10px;
    border-radius: 7px;
    color: inherit;
    text-decoration: none;
  }
  .item:hover {
    background: var(--muted);
  }
  .what {
    display: flex;
    flex: 1;
    min-width: 0;
    flex-direction: column;
    color: inherit;
    text-decoration: none;
  }
  .what b {
    font-weight: 600;
  }
  .where {
    overflow: hidden;
    color: var(--muted-foreground);
    font-size: 11.5px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .dot {
    flex: none;
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }
  .sep {
    height: 1px;
    margin: 6px 4px;
    background: var(--border);
  }
  .quiet {
    padding: 8px 10px;
    color: var(--muted-foreground);
  }
  .foot {
    display: flex;
    justify-content: space-between;
    padding: 6px 10px;
    border-radius: 7px;
    color: inherit;
    font-weight: 550;
    text-decoration: none;
  }
  .foot:hover {
    background: var(--muted);
  }
</style>
