<script lang="ts">
  // Areas (D.19): Work, Personal, a client. A project may have one; then only the accounts and
  // providers made for it (Model access) run its agents: a work account never on a personal
  // project. Nothing else is split by area (knowledge, addons, skills are shared). Each has a
  // colour, shown on its projects and tags; kept while a project, an account or a provider names
  // it. None yet: what they are for, how they work, and Work and Personal in one click. Then a
  // list, each area made and changed in a dialog (its name stays: the files name it).
  import Plus from "@lucide/svelte/icons/plus";
  import Tags from "@lucide/svelte/icons/tags";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { api } from "../lib/api";
  import { COLORS, areas } from "../lib/areas.svelte";
  import type { AreaInfo, AreaRequest } from "../lib/contracts.gen";
  import { href } from "../lib/router.svelte";
  import Dialog from "./Dialog.svelte";

  type Color = AreaRequest["color"];
  // the dialog open: a new area, or one's colour
  let panel = $state<{ kind: "new" } | { kind: "edit"; area: AreaInfo } | null>(null);
  let name = $state("");
  let color = $state<Color>(COLORS[0]!);
  let busy = $state(false);
  let error = $state<string | null>(null);

  void areas.load();

  async function run(action: () => Promise<unknown>): Promise<boolean> {
    busy = true;
    error = null;
    try {
      await action();
      await areas.load();
      return true;
    } catch (e) {
      error = (e as Error).message;
      return false;
    } finally {
      busy = false;
    }
  }

  function open(next: typeof panel): void {
    error = null;
    panel = next;
    name = "";
    color = next?.kind === "edit" ? next.area.color : (COLORS.find((c) => !areas.list.some((a) => a.color === c)) ?? COLORS[0]!);
  }

  async function save(): Promise<void> {
    const done =
      panel?.kind === "edit"
        ? await run(() => api.updateArea({ name: panel?.kind === "edit" ? panel.area.name : "", color }))
        : await run(() => api.createArea({ name: name.trim(), color }));
    if (done) panel = null;
  }

  /** The first run's shortcut: Work and Personal, each in its own colour. */
  function starters(): Promise<boolean> {
    return run(async () => {
      await api.createArea({ name: "Work", color: "blue" });
      await api.createArea({ name: "Personal", color: "violet" });
    });
  }

  async function remove(a: AreaInfo): Promise<void> {
    if (confirm(`Delete the area ${a.name}?`) && (await run(() => api.deleteArea(a.name)))) panel = null;
  }

  const users = (a: AreaInfo) => [...(a.projects ?? []), ...(a.accounts ?? []), ...(a.providers ?? [])];
  const count = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;
  /** What is in it, in one line: how many projects, accounts and providers. */
  const summary = (a: AreaInfo) =>
    users(a).length
      ? [
          a.projects?.length ? count(a.projects.length, "project") : null,
          a.accounts?.length ? count(a.accounts.length, "account") : null,
          a.providers?.length ? count(a.providers.length, "provider") : null,
        ]
          .filter(Boolean)
          .join(" · ")
      : "nothing in it yet";
</script>

{#snippet swatches()}
  <div class="flex gap-2" role="radiogroup" aria-label="Colour">
    {#each COLORS as c (c)}
      <button
        type="button"
        role="radio"
        aria-checked={color === c}
        aria-label={c}
        title={c}
        class="area-{c} size-8 rounded-full ring-offset-2 ring-offset-background transition-transform hover:scale-110 {color === c ? 'ring-2 ring-foreground' : ''}"
        style="background: var(--area)"
        onclick={() => (color = c)}
        data-testid="area-color-{c}"
      ></button>
    {/each}
  </div>
{/snippet}

{#snippet step(n: number, title: string, text: string, link?: { label: string; to: string })}
  <li class="flex gap-3">
    <span class="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted font-mono text-xs text-muted-foreground">{n}</span>
    <div class="space-y-0.5 pt-0.5">
      <p class="font-medium">{title}</p>
      <p class="text-muted-foreground">
        {text}
        {#if link}<a class="text-link hover:underline" href={link.to}>{link.label}</a>{/if}
      </p>
    </div>
  </li>
{/snippet}

<section class="space-y-10" data-testid="areas">
  {#if areas.list.length === 0}
    <!-- none yet: what they are for, how they work, and a start in one click -->
    <div class="enter rounded-[10px] border bg-card p-6 shadow-panel">
      <div class="flex items-start gap-4">
        <span class="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground"><Tags class="size-5" /></span>
        <div class="space-y-1">
          <h2 class="text-base font-semibold">Keep work and personal apart</h2>
          <p class="max-w-xl text-sm text-muted-foreground">
            An area is a side of your life: Work, Personal, a client. Each project can belong to one, and only the accounts made for its area run
            its agents, so your work subscription never runs on a personal project. Optional.
          </p>
        </div>
      </div>
      <ol class="mt-6 space-y-4 text-sm sm:pl-14">
        {@render step(1, "Make your areas", "One per side of your life, each with its colour.")}
        {@render step(2, "Give each project its area", "In the project's settings. Its agents then show the area's colour.")}
        {@render step(3, "Say which accounts each area may use", "For each account and provider, in", {
          label: "Model access",
          to: href({ view: "settings", section: "models" }),
        })}
      </ol>
      <div class="mt-6 flex flex-wrap items-center gap-2 sm:pl-14">
        <Button size="sm" disabled={busy} onclick={() => void starters()} data-testid="area-starters">Add Work and Personal</Button>
        <Button variant="outline" size="sm" onclick={() => open({ kind: "new" })} data-testid="area-new"><Plus />Another area</Button>
        <span class="text-xs text-muted-foreground">Knowledge folders, addons and skills stay shared by every area.</span>
      </div>
      {#if error && !panel}<p class="mt-4 text-sm text-danger sm:pl-14" data-testid="area-error">{error}</p>{/if}
    </div>
  {:else}
    <div class="space-y-4">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <p class="max-w-2xl text-sm text-muted-foreground">
          A project in an area runs only the accounts and providers made for it (set in
          <a class="text-link hover:underline" href={href({ view: "settings", section: "models" })}>Model access</a>). Knowledge, addons and skills stay
          shared.
        </p>
        <Button variant="outline" size="sm" onclick={() => open({ kind: "new" })} data-testid="area-new"><Plus />Add an area</Button>
      </div>
      {#if error && !panel}<p class="text-sm text-danger" data-testid="area-error">{error}</p>{/if}
      <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
        {#each areas.list as a (a.name)}
          <li class="enter flex items-center gap-4 px-4 py-3.5 area-{a.color}" data-testid="area-row">
            <span class="flex size-9 shrink-0 items-center justify-center rounded-lg" style="background: var(--area-soft)">
              <span class="size-3 rounded-full" style="background: var(--area)"></span>
            </span>
            <div class="min-w-0 flex-1 space-y-0.5">
              <p class="truncate font-medium">{a.name}</p>
              <p class="fact">{summary(a)}</p>
            </div>
            <Button variant="ghost" size="sm" onclick={() => open({ kind: "edit", area: a })} data-testid="area-edit">Edit</Button>
          </li>
        {/each}
      </ul>
    </div>
  {/if}
  {#if areas.error}<p class="text-sm text-danger">{areas.error}</p>{/if}

  <Dialog
    bind:open={() => panel !== null, (v) => (v ? null : (panel = null))}
    title={panel?.kind === "edit" ? panel.area.name : "New area"}
    description={panel?.kind === "edit"
      ? users(panel.area).length
        ? [
            panel.area.projects?.length ? `Projects: ${panel.area.projects.join(", ")}.` : "",
            panel.area.accounts?.length || panel.area.providers?.length
              ? `Made for it: ${[...(panel.area.accounts ?? []), ...(panel.area.providers ?? [])].join(", ")}.`
              : "",
          ]
            .filter(Boolean)
            .join(" ")
        : "Nothing in it yet."
      : "A side of your life: Work, Personal, a client."}
    testid="area-dialog"
  >
    <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void save())}>
      {#if panel?.kind === "new"}
        <div class="space-y-1.5">
          <Label for="area-name">Name</Label>
          <Input id="area-name" placeholder="Work, Personal, a client…" maxlength={32} bind:value={name} required data-testid="area-name" />
          <p class="text-xs text-muted-foreground">It cannot change later: projects and accounts name it.</p>
        </div>
      {/if}
      <div class="space-y-2">
        <span class="text-sm font-medium">Colour</span>
        {@render swatches()}
        <p class="text-xs text-muted-foreground">Its projects' icons and its tags show it.</p>
      </div>
      {#if error}<p class="text-danger" data-testid="area-error">{error}</p>{/if}
      {#if panel?.kind === "edit" && users(panel.area).length}
        <p class="text-xs text-muted-foreground">To delete it, take it off its projects, accounts and providers first.</p>
      {/if}
      <div class="flex flex-wrap items-center gap-2 border-t pt-4">
        {#if panel?.kind === "edit"}
          {@const a = panel.area}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            class="text-destructive hover:text-destructive"
            disabled={busy || users(a).length > 0}
            onclick={() => void remove(a)}
            data-testid="area-delete">Delete</Button
          >
        {/if}
        <span class="flex-1"></span>
        <Button type="button" variant="ghost" size="sm" onclick={() => (panel = null)}>Cancel</Button>
        <Button type="submit" size="sm" disabled={busy || (panel?.kind === "new" && !name.trim())} data-testid="area-add">
          {panel?.kind === "edit" ? "Save" : "Add"}
        </Button>
      </div>
    </form>
  </Dialog>
</section>
