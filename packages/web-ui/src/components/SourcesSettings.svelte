<script lang="ts">
  // Sources (D.26): the git repositories apps, agents and addons are offered from. Handler's own
  // first (always there), then those you added, each a row: its name, where it is, when it was
  // read and what it offers; Read again, and Remove for one you added (what you installed from it
  // stays). Adding one is a dialog that says plainly that Handler does not check what is in it:
  // you tick that you trust it. What a source offers is installed where it is used (Apps,
  // Library → Addons, a project's agents), never here.
  import Plus from "@lucide/svelte/icons/plus";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import Store from "@lucide/svelte/icons/store";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import Dialog from "./Dialog.svelte";
  import When from "./When.svelte";
  import { api } from "../lib/api";
  import type { Source } from "../lib/contracts.gen";

  let sources = $state<Source[] | null>(null);
  let adding = $state(false); // the dialog open
  let url = $state("");
  let trusted = $state(false);
  let busy = $state<string | null>(null); // what is being read: a source's id, or "add"
  let error = $state<string | null>(null);
  let removing = $state<Source | null>(null); // the one Remove was pressed on
  let confirming = $state(false); // its dialog open

  api.sources().then(
    (s) => (sources = s),
    (e: Error) => (error = e.message),
  );

  const KINDS = { app: ["app", "apps"], agents: ["agents file", "agents files"], addon: ["addon", "addons"] } as const;

  /** "1 app, 2 addons": what it offers that can be installed. */
  function offers(s: Source): string {
    const items = (s.items ?? []).filter((i) => !i.error);
    const counts = (Object.keys(KINDS) as (keyof typeof KINDS)[])
      .map((k) => [k, items.filter((i) => i.kind === k).length] as const)
      .filter(([, n]) => n > 0)
      .map(([k, n]) => `${n} ${KINDS[k][n === 1 ? 0 : 1]}`);
    return counts.length ? counts.join(", ") : "nothing to install yet";
  }

  const unreadable = (s: Source) => (s.items ?? []).filter((i) => i.error);

  async function refresh(s: Source): Promise<void> {
    busy = s.id;
    error = null;
    try {
      const read = await api.refreshSource(s.id);
      sources = (sources ?? []).map((x) => (x.id === s.id ? read : x));
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = null;
    }
  }

  async function add(): Promise<void> {
    busy = "add";
    error = null;
    try {
      const added = await api.addSource(url.trim());
      sources = [...(sources ?? []), added];
      adding = false;
      url = "";
      trusted = false;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = null;
    }
  }

  async function remove(s: Source): Promise<void> {
    busy = s.id;
    error = null;
    try {
      await api.removeSource(s.id);
      sources = (sources ?? []).filter((x) => x.id !== s.id);
      confirming = false;
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = null;
    }
  }
</script>

<section class="space-y-4" data-testid="sources">
  <div class="flex flex-wrap items-end justify-between gap-3">
    <p class="max-w-2xl text-sm text-muted-foreground">
      Where apps, agents and addons come from: Handler's own, and any you add. You install what they offer where you use it: Apps, Library → Addons, a
      project's agents.
    </p>
    <Button variant="outline" size="sm" onclick={() => ((adding = true), (error = null))} data-testid="source-new"><Plus />Add a source</Button>
  </div>
  {#if error && !adding && !confirming}<p class="text-sm text-danger" data-testid="source-error">{error}</p>{/if}
  {#if sources}
    <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
      {#each sources as s (s.id)}
        {@const bad = unreadable(s)}
        <li class="flex items-center gap-4 px-4 py-3.5" data-testid="source">
          <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:flex"><Store class="size-4" /></span>
          <div class="min-w-0 flex-1 space-y-0.5">
            <p class="flex flex-wrap items-center gap-2">
              <span class="font-medium" data-testid="source-name">{s.official ? "Handler" : (s.name ?? s.id)}</span>
              <span class="rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{s.official ? "reviewed by Handler" : "added by you"}</span>
              {#if s.error}
                <span class="inline-flex items-center gap-1 rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn" title={s.error} data-testid="source-problem"
                  ><TriangleAlert class="size-3" />{s.commit ? "not read again" : "cannot be read"}</span
                >
              {:else if bad.length}
                <span class="inline-flex items-center gap-1 rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn" title={bad.map((i) => `${i.name}: ${i.error}`).join("\n")}
                  ><TriangleAlert class="size-3" />{bad.length} not offered</span
                >
              {/if}
            </p>
            {#if s.description}<p class="text-muted-foreground">{s.description}</p>{/if}
            <p class="fact truncate" title={s.url}>{s.url} · {offers(s)} · read <When at={s.fetchedAt} /></p>
          </div>
          <Button variant="ghost" size="sm" disabled={busy !== null} onclick={() => refresh(s)} aria-label={`Read ${s.official ? "Handler" : s.id} again`} data-testid="source-refresh"
            ><RefreshCw class={busy === s.id ? "animate-spin" : ""} />Read again</Button
          >
          {#if !s.official}
            <Button variant="ghost" size="sm" class="text-muted-foreground hover:text-destructive" disabled={busy !== null} onclick={() => ((removing = s), (confirming = true), (error = null))} data-testid="source-remove"
              >Remove</Button
            >
          {/if}
        </li>
      {/each}
    </ul>
  {:else if !error}
    <p class="fact">Reading the sources…</p>
  {/if}

  <Dialog bind:open={adding} title="Add a source" description="A git repository that offers apps, agents or addons." testid="source-dialog">
    <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void add())}>
      <div class="space-y-1.5">
        <Label for="source-url">Its address</Label>
        <Input id="source-url" class="font-mono text-sm" placeholder="https://github.com/someone/their-source" bind:value={url} data-testid="source-url" />
        <p class="text-xs text-muted-foreground">An https:// address. Handler reads it first: it must have a <span class="font-mono">handler-source.toml</span>.</p>
      </div>
      <p class="flex items-start gap-2.5 rounded-[10px] border border-warn/40 bg-warn/5 p-3 text-warn">
        <TriangleAlert class="mt-0.5 size-4 shrink-0" />
        <span>Handler does not check what is in a source you add. What you install from it runs on this computer, within what its install page shows.</span>
      </p>
      <label class="flex items-start gap-3"
        ><Checkbox checked={trusted} onCheckedChange={(v) => (trusted = v === true)} data-testid="source-trust" /><span>I trust whoever writes this source</span></label
      >
      {#if error}<p class="text-danger" data-testid="source-error">{error}</p>{/if}
      <div class="flex justify-end gap-2 border-t pt-4">
        <Button type="button" variant="ghost" size="sm" onclick={() => (adding = false)}>Cancel</Button>
        <Button type="submit" size="sm" disabled={busy !== null || !trusted || !url.trim().startsWith("https://")} data-testid="source-add"
          >{busy === "add" ? "Reading it…" : "Add"}</Button
        >
      </div>
    </form>
  </Dialog>

  <Dialog bind:open={confirming} title={`Remove ${removing?.name ?? removing?.id ?? ""}?`} description="Nothing more is offered from it. What you installed from it stays: it is yours." testid="source-remove-dialog">
    {#if error}<p class="text-danger">{error}</p>{/if}
    <div class="flex justify-end gap-2 border-t pt-4">
      <Button variant="ghost" size="sm" onclick={() => (confirming = false)}>Cancel</Button>
      <Button variant="destructive" size="sm" disabled={busy !== null} onclick={() => removing && remove(removing)} data-testid="source-remove-confirm">Remove</Button>
    </div>
  </Dialog>
</section>
