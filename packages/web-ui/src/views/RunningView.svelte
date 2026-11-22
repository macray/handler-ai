<script lang="ts">
  // Running: every running session, across projects (lib/running.svelte.ts). The bar: the project
  // chips (All, then each project with something running: they only filter), the hidden
  // sessions, the layout (One, Columns, Grid), full screen (the menu folded), "+" (a new-session
  // pane). The stage: the panes (SessionPane), one of them with the focus and the composer; in
  // One the focused one alone, its title a switcher. At its foot, the terminals of `handler
  // terminal` (D.16), each a line whose Network opens beside the stage. `#/sessions/:key` is
  // One with that session (`focus`, `panel`: its side panel open); `terminal`: that terminal's network open. Empty: "Nothing is
  // running." and the new-session form, or with no model yet, its Connect (ConnectFirst).
  import { onDestroy, untrack } from "svelte";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import Columns2 from "@lucide/svelte/icons/columns-2";
  import EyeOff from "@lucide/svelte/icons/eye-off";
  import LayoutGrid from "@lucide/svelte/icons/layout-grid";
  import Maximize from "@lucide/svelte/icons/maximize";
  import Minimize from "@lucide/svelte/icons/minimize";
  import Plus from "@lucide/svelte/icons/plus";
  import Square from "@lucide/svelte/icons/square";
  import SquareTerminal from "@lucide/svelte/icons/square-terminal";
  import X from "@lucide/svelte/icons/x";
  import * as SidebarUI from "$lib/components/ui/sidebar";
  import Bell from "../components/Bell.svelte";
  import ConnectFirst from "../components/ConnectFirst.svelte";
  import NetworkPanel from "../components/NetworkPanel.svelte";
  import NewSessionForm from "../components/NewSessionForm.svelte";
  import Popover from "../components/Popover.svelte";
  import SessionPane from "../components/SessionPane.svelte";
  import SessionStatus from "../components/SessionStatus.svelte";
  import { duration } from "@handler/acp-view/lib/tools";
  import { accessLabel } from "../lib/access";
  import { question } from "../lib/bell.svelte";
  import type { Agent } from "../lib/contracts.gen";
  import { agentLabel, projects } from "../lib/projects.svelte";
  import { areas } from "../lib/areas.svelte";
  import { emptyFor } from "../lib/menu";
  import { menuUse } from "../lib/menuuse.svelte";
  import { href, navigate } from "../lib/router.svelte";
  import { byState, gridShape, onStage, running, sinceLabel, spans, waitingSince, type Layout, type NewPane } from "../lib/running.svelte";
  import { sessions, STATUS_LABEL, type LiveSession } from "../lib/sessions.svelte";

  let { focus, panel, terminal }: { focus?: string; panel?: "files" | "network"; terminal?: string } = $props();

  const sidebar = SidebarUI.useSidebar();

  // the route's session: One with it, focused; one this browser does not know yet (a link) is
  // adopted: shown and attached
  $effect(() => {
    if (focus) untrack(() => (running.focus = focus));
  });
  $effect(() => {
    if (focus && sessions.restored && !sessions.get(focus)) void sessions.adopt(focus);
  });

  const empty = $derived(emptyFor({ known: menuUse.modelKnown, ready: menuUse.modelReady }));
  const layout = $derived<Layout>(focus ? "one" : running.prefs.layout);
  const folded = $derived(running.prefs.folded);

  // full screen: the menu folded while on Running, given back when leaving it
  $effect(() => {
    const fold = folded;
    untrack(() => sidebar.setOpen(!fold));
  });
  onDestroy(() => {
    if (running.prefs.folded) sidebar.setOpen(true);
  });

  type Item = { key: string; project: string | null; needsYou: boolean; session?: LiveSession; draft?: NewPane };
  // needs you first, the latest to ask first, then as dragged: a tile moves only when its state
  // changes (`asked`: when each started to need you, noted here, not state: read as it derives)
  let asked: Record<string, number> = {};
  let asks = 0;
  const items = $derived.by<Item[]>(() => {
    const all = running.sessions.map((s) => ({ key: s.key, project: s.agent.projectId ?? "", needsYou: s.status === "needs-you", session: s }));
    asked = waitingSince(asked, all.filter((x) => x.needsYou).map((x) => x.key), () => ++asks);
    return byState(all, running.prefs.order, asked);
  });
  const stage = $derived(onStage(items, running.chip, running.prefs.hidden));
  const panes = $derived<Item[]>([...stage.shown, ...running.drafts.map((d) => ({ key: d.key, project: d.project, needsYou: false, draft: d }))]);
  const shape = $derived(gridShape(panes.length));
  const widths = $derived(spans(panes.length, shape.cols));

  // One: a new-session pane just added, else the route's session, else the focus, else the first
  const one = $derived.by((): Item | undefined => {
    const f = running.focus;
    const draft = running.drafts.find((d) => d.key === f);
    if (draft) return { key: draft.key, project: draft.project, needsYou: false, draft };
    const key = focus ?? (f && sessions.get(f) ? f : panes[0]?.key);
    const s = key ? sessions.get(key) : undefined;
    return s ? { key: s.key, project: s.agent.projectId ?? "", needsYou: s.status === "needs-you", session: s } : undefined;
  });

  // One in full screen: the bar folded too, its control in the session's caption (`lead`); a
  // new-session pane, or no session, has no caption: the bar stays, or there is no way out
  const bare = $derived(layout === "one" && folded && !!one?.session);

  // what is kept forgets the sessions no longer running (once the daemon's list is known)
  $effect(() => {
    if (sessions.polled) untrack(() => running.prune(sessions.list.filter((s) => s.status !== "stopped").map((s) => s.key)));
  });

  // arriving: the first pane has the focus (not a session started elsewhere's: that one becomes
  // this browser's only when clicked)
  $effect(() => {
    const keys = panes.map((p) => p.key);
    if (layout !== "one" && keys.length && !keys.includes(running.focus ?? "")) untrack(() => (running.focus = keys[0]!));
  });

  /** A pane clicked: it gets the focus (and a session started elsewhere becomes this browser's). */
  function focusPane(key: string): void {
    running.focus = key;
    const s = sessions.get(key);
    if (s) sessions.view(s);
  }

  function setLayout(l: Layout): void {
    running.setLayout(l);
    if (l !== "one" && focus) navigate({ view: "running" });
    else if (l === "one" && !focus && running.focus && sessions.get(running.focus)) navigate({ view: "session", key: running.focus });
  }

  /** "All running": the stage again, in the layout kept (Grid when One was). */
  function all(): void {
    if (running.prefs.layout === "one") running.setLayout("grid");
    navigate({ view: "running" });
  }

  function add(): void {
    running.add(running.chip ?? null);
  }

  function started(draft: NewPane, s: LiveSession): void {
    running.drop(draft.key, s.key);
    if (layout === "one") navigate({ view: "session", key: s.key });
  }

  function ended(key: string): void {
    if (running.focus === key) running.focus = null;
    if (layout === "one") all();
  }

  // dragging a pane by its header onto another's place
  let dragged = $state<string | null>(null);
  let over = $state<string | null>(null);
  function drop(to: string): void {
    if (dragged && dragged !== to) running.move(panes.map((p) => p.key), dragged, to);
    dragged = over = null;
  }

  // the chips: All, then each project with something running (hidden ones counted), by name
  const terminalsAll = $derived(running.terminals);
  const chips = $derived.by(() => {
    const n = new Map<string, number>();
    if (running.chip !== undefined) n.set(running.chip, 0); // the one chosen stays, even with nothing left
    for (const x of [...items.map((i) => i.project ?? ""), ...terminalsAll.map((t) => t.agent.projectId ?? "")]) n.set(x, (n.get(x) ?? 0) + 1);
    const name = (id: string) => projects.get(id)?.name ?? (id ? "a project" : "outside projects");
    return [...n.entries()].map(([id, count]) => ({ id, count, name: name(id), area: projects.get(id)?.area })).sort((a, b) => a.name.localeCompare(b.name));
  });
  const total = $derived(items.length + terminalsAll.length);

  const terminals = $derived(terminalsAll.filter((t) => running.chip === undefined || (t.agent.projectId ?? "") === running.chip));
  const network = $derived(terminal ? terminalsAll.find((t) => t.conn.id === terminal) : undefined);
  const networkFor = (id: string) => href({ view: "running", terminal: id });
  let changed = $state<Agent | null>(null); // the agent as its network panel last saved it
  const networkAgent = $derived(network && changed?.id === network.agent.id ? changed : network?.agent);

  const projectName = (s: LiveSession) => projects.of(s.agent)?.project.name ?? "outside projects";
  let now = $state(Date.now());
  $effect(() => {
    const timer = setInterval(() => (now = Date.now()), 15000);
    return () => clearInterval(timer);
  });
  const since = (iso: string) => duration(now - Date.parse(iso)).replace(/(\d+[hm])\d+[ms]$/, "$1");

  // the switcher's groups: what needs you, then each project's sessions and terminals
  const needYou = $derived(items.filter((i) => i.needsYou && i.session).map((i) => i.session!));
  const groups = $derived(
    chips.map((c) => ({
      ...c,
      sessions: items.filter((i) => (i.project ?? "") === c.id && i.session).map((i) => i.session!),
      terminals: terminalsAll.filter((t) => (t.agent.projectId ?? "") === c.id),
    })),
  );
  let switching = $state(false);
  let hiddenOpen = $state(false);
  const LAYOUT_LABEL: Record<Layout, string> = { one: "One", columns: "Columns", grid: "Grid" };
</script>

<!-- the title in One: the switcher (needs you first, then each project's, All running, New session) -->
{#snippet switcher(s: LiveSession)}
  <Popover bind:open={switching} label="Running sessions" width="26rem" testid="switcher">
    {#snippet trigger(props)}
      <button type="button" class="switch" {...props} data-testid="switcher-toggle"><h1>{s.title ?? agentLabel(s.agent)}</h1><ChevronDown class="size-4 flex-none opacity-70" /></button>
    {/snippet}
    {#snippet children(close)}
      {#if needYou.length}
        <p class="group">Needs you</p>
        {#each needYou as w (w.key)}
          {@const q = question(w)}
          <a class="row warn" href={href({ view: "session", key: w.key })} onclick={close} data-testid="switcher-needs-you"
            ><SessionStatus status="needs-you" /><span class="row-title">{w.title ?? agentLabel(w.agent)}</span><span class="row-note"
              >{projectName(w)} · {q ? `asks to ${q.title}` : agentLabel(w.agent)}</span
            ></a
          >
        {/each}
      {/if}
      {#each groups as g (g.id)}
        <p class="group"><span class="swatch {areas.colorClass(g.area)}" aria-hidden="true"></span>{g.name}</p>
        {#each g.sessions as o (o.key)}
          {@const isHidden = running.prefs.hidden.includes(o.key)}
          <a class="row" class:current={o.key === s.key} class:faint={isHidden} href={href({ view: "session", key: o.key })} onclick={close} data-testid="switcher-session"
            ><SessionStatus status={o.status} /><span class="row-title">{o.title ?? agentLabel(o.agent)}</span><span class="row-note"
              >{isHidden ? "hidden" : [STATUS_LABEL[o.status], sinceLabel(o, now)].filter(Boolean).join(" · ")}</span
            ></a
          >
        {/each}
        {#each g.terminals as t (t.conn.id)}
          <a class="row" href={networkFor(t.conn.id)} onclick={close} data-testid="switcher-terminal"
            ><SquareTerminal class="size-3.5 flex-none" /><span class="row-title">{agentLabel(t.agent)}, in your terminal</span><span class="row-note">{since(t.conn.since)}</span></a
          >
        {/each}
      {/each}
      <div class="sep"></div>
      <button type="button" class="row" onclick={() => (close(), all())} data-testid="switcher-all"
        ><LayoutGrid class="size-3.5 flex-none" /><span class="row-title">All running</span><span class="row-note"
          >back to {LAYOUT_LABEL[running.prefs.layout === "one" ? "grid" : running.prefs.layout]}</span
        ></button
      >
      <button type="button" class="row accent" onclick={() => (close(), add())} data-testid="switcher-new"><Plus class="size-3.5 flex-none" /><span class="row-title">New session</span></button>
    {/snippet}
  </Popover>
{/snippet}

<!-- full screen's small control, top left: out of full screen (One: the bar is folded too), +,
     and the bell standing in for the folded menu -->
{#snippet control(withExit: boolean)}
  <div class="control" data-testid="fullscreen-control">
    {#if withExit}
      <button type="button" class="icon" onclick={() => running.setFolded(false)} aria-label="Exit full screen" title="Exit full screen" data-testid="fullscreen-exit"><Minimize class="size-4" /></button>
      <button type="button" class="icon" onclick={add} aria-label="New session" title="New session"><Plus class="size-4" /></button>
    {/if}
    <Bell />
  </div>
{/snippet}

{#snippet newPane(d: NewPane, isFocused: boolean)}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="new-pane term-surface" class:focused={isFocused} onpointerdown={() => (running.focus = d.key)} data-testid="new-session-pane">
    <header class="new-bar">
      <Plus class="size-4 text-primary" /><span class="font-semibold">New session</span>
      <button type="button" class="icon ml-auto" onclick={() => running.drop(d.key)} aria-label="Remove" title="Remove" data-testid="new-session-close"><X class="size-4" /></button>
    </header>
    <div class="new-body"><NewSessionForm project={d.project} onstarted={(s) => started(d, s)} /></div>
  </div>
{/snippet}

{#snippet pane(item: Item, full: boolean)}
  {#if item.draft}
    {@render newPane(item.draft, full || running.focus === item.key)}
  {:else if item.session}
    <SessionPane
      session={item.session}
      {full}
      opens={full && item.key === focus ? panel : undefined}
      focused={full || running.focus === item.key}
      back={stage.back.has(item.key)}
      onfocus={() => focusPane(item.key)}
      onhide={() => running.hide(item.key)}
      onalone={() => navigate({ view: "session", key: item.key })}
      onended={ended}
      title={full ? titleOf : undefined}
      lead={full && folded ? lead : undefined}
      dragstart={full ? undefined : (e) => ((dragged = item.key), e.dataTransfer?.setData("text/plain", item.key))}
    />
  {/if}
{/snippet}
{#snippet titleOf()}{#if one?.session}{@render switcher(one.session)}{/if}{/snippet}
{#snippet lead()}{@render control(true)}{/snippet}

<div class="running" class:bare data-testid="running" data-layout={layout}>
  {#if !bare}
    <div class="bar" data-testid="running-bar">
      {#if folded}{@render control(false)}{/if}
      {#if total || running.chip !== undefined}<div class="chips" role="group" aria-label="Projects">
        <button type="button" class="chip" aria-pressed={running.chip === undefined} onclick={() => (running.chip = undefined)} data-testid="chip-all">All <span class="n">{total}</span></button>
        {#each chips as c (c.id)}
          <button type="button" class="chip" aria-pressed={running.chip === c.id} onclick={() => (running.chip = c.id)} data-testid="chip"
            ><span class="swatch {areas.colorClass(c.area)}" aria-hidden="true"></span>{c.name} <span class="n">{c.count}</span></button
          >
        {/each}
      </div>{/if}
      {#if stage.hidden.length}
        <Popover bind:open={hiddenOpen} label="Hidden from All running" width="22rem" testid="hidden-list">
          {#snippet trigger(props)}
            <button type="button" class="hidden-toggle" {...props} data-testid="hidden-toggle"><EyeOff class="size-3.5" />{stage.hidden.length} hidden<ChevronDown class="size-3.5" /></button>
          {/snippet}
          {#snippet children(close)}
            <p class="group">Hidden from All running</p>
            {#each stage.hidden as h (h.key)}
              <div class="row">
                {#if h.session}<SessionStatus status={h.session.status} /><span class="row-title">{h.session.title ?? agentLabel(h.session.agent)}</span><span class="row-note">{projectName(h.session)}</span>{/if}
                <button type="button" class="text-link" onclick={() => running.show(h.key)} data-testid="hidden-show">Show</button>
              </div>
            {/each}
            <div class="sep"></div>
            <button type="button" class="row text-link" onclick={() => (running.showAll(), close())} data-testid="hidden-show-all">Show all</button>
          {/snippet}
        </Popover>
      {/if}
      <div class="ml-auto flex items-center gap-2">
        <div class="layouts" role="group" aria-label="Layout">
          {#each [["one", Square], ["columns", Columns2], ["grid", LayoutGrid]] as const as [l, Icon] (l)}
            <button type="button" aria-pressed={layout === l} onclick={() => setLayout(l)} data-testid="layout-{l}"><Icon class="size-3.5" />{LAYOUT_LABEL[l]}</button>
          {/each}
        </div>
        <button
          type="button"
          class="icon boxed"
          aria-pressed={folded}
          onclick={() => running.setFolded(!folded)}
          aria-label={folded ? "Exit full screen" : "Full screen"}
          title={folded ? "Exit full screen" : "Full screen: the menu folded"}
          data-testid="fullscreen">{#if folded}<Minimize class="size-4" />{:else}<Maximize class="size-4" />{/if}</button
        >
        <button type="button" class="icon plus" onclick={add} aria-label="New session" title="New session" data-testid="running-new"><Plus class="size-4" /></button>
      </div>
    </div>
  {/if}

  <div class="stage-row">
    {#if !panes.length && !(layout === "one" && one)}
      <div class="empty term-surface" data-testid="running-empty">
        {#if !sessions.restored || !empty}
          <p class="text-muted-foreground">Loading…</p>
        {:else}
          <p class="empty-title">{stage.hidden.length ? `Nothing shown: ${stage.hidden.length} hidden.` : "Nothing is running."}</p>
          {#if empty === "no-model"}<ConnectFirst testid="running-connect" center />{:else}<NewSessionForm project={running.chip ?? null} onstarted={(s) => (running.focus = s.key)} />{/if}
        {/if}
      </div>
    {:else if layout === "one"}
      <div class="stage one">
        {#if one}{@render pane(one, true)}{:else}<p class="p-6 text-sm text-muted-foreground">This session is not running any more.</p>{/if}
      </div>
    {:else}
      <div
        class="stage {layout}"
        style:--rows={Math.min(shape.rows, 3)}
        data-testid="stage"
        data-cols={layout === "grid" ? shape.cols : panes.length}
      >
        {#each panes as p, i (p.key)}
          <div
            class="slot"
            class:drop-here={over === p.key && dragged !== p.key}
            style:grid-column={layout === "grid" ? `span ${widths[i]}` : null}
            role="listitem"
            ondragover={(e) => {
              if (!dragged) return;
              e.preventDefault();
              over = p.key;
            }}
            ondragend={() => (dragged = over = null)}
            ondrop={(e) => {
              e.preventDefault();
              drop(p.key);
            }}
          >
            {@render pane(p, false)}
          </div>
        {/each}
      </div>
    {/if}
    {#if network}
      <aside class="network term-surface" data-testid="terminal-network">
        <header class="new-bar">
          <SquareTerminal class="size-4" /><span class="font-semibold">{agentLabel(network.agent)}, in your terminal</span>
          <a class="icon ml-auto" href={href({ view: "running" })} aria-label="Close" title="Close" data-testid="terminal-network-close"><X class="size-4" /></a>
        </header>
        <div class="network-body">
          <NetworkPanel
            agent={networkAgent ?? network.agent}
            session={{ harness: network.conn.terminal.harness ?? "", account: network.conn.terminal.account, provider: network.conn.terminal.provider }}
            onchange={(a) => (changed = a)}
          />
        </div>
      </aside>
    {/if}
  </div>

  {#each terminals as t (t.conn.id)}
    <div class="terminal-line" title={accessLabel(t.conn.terminal)} data-testid="terminal-line">
      <SquareTerminal class="size-4 flex-none text-muted-foreground" />
      <span class="italic">{agentLabel(t.agent)}, in your terminal</span>
      <span class="text-muted-foreground">· running {since(t.conn.since)} · you talk to it there</span>
      <a class="ml-auto text-link" href={networkFor(t.conn.id)} aria-current={terminal === t.conn.id ? "true" : undefined} data-testid="terminal-network-link">Network</a>
    </div>
  {/each}
</div>

<style>
  .running {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.6rem 0.6rem 0.6rem 0.5rem;
  }
  .running.bare {
    padding: 0;
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    min-height: 2.25rem;
    flex: none;
    font-size: 0.8125rem;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.3rem 0.75rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--card);
    font-weight: 500;
  }
  .chip[aria-pressed="true"] {
    border-color: var(--foreground);
    background: var(--foreground);
    color: var(--background);
  }
  .chip .n {
    font-family: var(--mono);
    font-size: 0.72rem;
    font-weight: 400;
    opacity: 0.7;
  }
  .swatch {
    width: 0.5rem;
    height: 0.5rem;
    flex: none;
    border-radius: 2px;
    background: var(--area, var(--muted-foreground));
  }
  .hidden-toggle {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    color: var(--link);
    font-weight: 500;
  }
  .layouts {
    display: flex;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--card);
    overflow: hidden;
  }
  .layouts button {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.3rem 0.7rem;
    color: var(--muted-foreground);
  }
  .layouts button + button {
    border-left: 1px solid var(--border);
  }
  .layouts button[aria-pressed="true"] {
    background: var(--muted);
    color: var(--foreground);
    font-weight: 600;
  }
  .icon {
    display: grid;
    place-items: center;
    width: 2rem;
    height: 2rem;
    border-radius: 8px;
    color: var(--muted-foreground);
  }
  .icon:hover {
    color: var(--foreground);
  }
  .icon.boxed {
    border: 1px solid var(--border);
    background: var(--card);
  }
  .icon.boxed[aria-pressed="true"] {
    border-color: var(--primary);
    color: var(--primary);
  }
  .icon.plus {
    background: var(--primary);
    color: var(--primary-foreground);
  }
  .control {
    display: flex;
    flex: none;
    align-items: center;
    gap: 0.15rem;
    padding: 0.15rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--card);
  }
  .control .icon {
    width: 1.75rem;
    height: 1.75rem;
  }
  .stage-row {
    flex: 1;
    min-height: 0;
    display: flex;
    gap: 0.5rem;
  }
  .stage {
    flex: 1;
    min-width: 0;
    min-height: 0;
  }
  .stage.one {
    display: flex;
    flex-direction: column;
  }
  .running:not(.bare) .stage.one {
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }
  /* Grid: six tracks (a pane spans 2, 3 or 6: lib/running spans), up to three rows in sight */
  .stage.grid {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    grid-auto-rows: calc((100% - (var(--rows) - 1) * 0.5rem) / var(--rows));
    gap: 0.5rem;
    overflow-y: auto;
  }
  /* Columns: side by side, scrolling sideways past the width */
  .stage.columns {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: minmax(26rem, 1fr);
    gap: 0.5rem;
    overflow-x: auto;
  }
  .slot {
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    border-radius: 10px;
  }
  .slot.drop-here {
    box-shadow: 0 0 0 2px var(--primary);
  }
  .new-pane {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }
  .new-pane.focused {
    border-color: var(--primary);
    box-shadow: 0 0 0 1px var(--primary);
  }
  .new-bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    height: 2.5rem;
    flex: none;
    padding: 0 0.4rem 0 0.75rem;
    border-bottom: 1px solid var(--border);
    font-family: var(--sans);
    font-size: 0.8125rem;
  }
  .new-body {
    flex: 1;
    min-height: 0;
    display: flex;
    overflow-y: auto;
    padding: 1.25rem 1rem;
  }
  .empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 1.25rem;
    border-radius: 10px;
    padding: 2rem;
  }
  .empty > :global(form) {
    margin: 0;
  }
  .empty-title {
    font-family: var(--sans);
    font-size: 1rem;
    font-weight: 600;
  }
  .network {
    width: 22rem;
    flex: none;
    display: flex;
    flex-direction: column;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }
  .network-body {
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
    font-family: var(--sans);
    font-size: 0.875rem;
  }
  .terminal-line {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex: none;
    padding: 0.5rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--card);
    font-size: 0.8125rem;
  }
  /* the switcher (One's title) */
  .switch {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    min-width: 0;
    max-width: 34rem;
    padding: 0.2rem 0.4rem;
    margin-left: -0.4rem;
    border-radius: 6px;
  }
  .switch:hover {
    background: var(--muted);
  }
  .switch h1 {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 600;
  }
  .group {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin: 0.5rem 0.5rem 0.25rem;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--muted-foreground);
  }
  .row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    padding: 0.35rem 0.5rem;
    border-radius: 6px;
    color: var(--foreground);
    font-size: 0.8125rem;
    text-align: left;
    text-decoration: none;
  }
  a.row:hover,
  button.row:hover,
  .row.current {
    background: var(--muted);
  }
  .row.warn .row-title {
    color: var(--warn);
  }
  .row.accent {
    color: var(--primary);
  }
  .row.faint {
    opacity: 0.5;
  }
  .row-title {
    min-width: 0;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .row-note {
    flex: none;
    max-width: 50%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--muted-foreground);
    font-size: 0.75rem;
  }
  .sep {
    height: 1px;
    margin: 0.35rem 0;
    background: var(--border);
  }
</style>
