<script lang="ts">
  // The Library's Apps shelf (contract H, apps design): get and manage apps; they open from Apps.
  // Yours: a row each (where it comes from, its version, its state; a new version to deploy, or
  // what it still needs, amber, with Fix: its page), then the drafts of new apps being written
  // with the App creator (H.15). Get more: what the sources offer (D.26, SourceShelf), making your
  // own with the App creator (on a draft kept by Handler, lib/drafts.ts) and installing an app
  // file (an export: a new app, or the next version of one you have). Installing goes through its
  // install page (AppInstallView).
  import AppWindow from "@lucide/svelte/icons/app-window";
  import FilePenLine from "@lucide/svelte/icons/file-pen-line";
  import FileUp from "@lucide/svelte/icons/file-up";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import WandSparkles from "@lucide/svelte/icons/wand-sparkles";
  import { Button } from "$lib/components/ui/button";
  import LoadingCards from "../components/LoadingCards.svelte";
  import HelperCard from "../components/HelperCard.svelte";
  import SourceShelf from "../components/SourceShelf.svelte";
  import StatusBadge from "../components/StatusBadge.svelte";
  import { missing } from "../lib/apps";
  import { api } from "../lib/api";
  import type { App, Session, Source } from "../lib/contracts.gen";
  import { continueDraft, draftsOf, startDraft, throwAway, useDraft } from "../lib/drafts";
  import { LIBRARY_WIDTH } from "../lib/library";
  import { href, navigate } from "../lib/router.svelte";
  import { fromSourceWords } from "../lib/sources";

  let { more = false }: { more?: boolean } = $props();

  let apps = $state<App[] | null>(null);
  let sources = $state<Source[]>([]);
  let drafts = $state<Session[]>([]); // of new apps, with the App creator
  let error = $state<string | null>(null);
  let creatorCard = $state(false); // no App creator yet: its set-up card
  let installing = $state(false);
  let picker = $state<HTMLInputElement>(); // the app file to install

  async function load(): Promise<void> {
    try {
      let list: Session[];
      [apps, list] = await Promise.all([api.apps(), api.sessions().catch(() => [])]);
      drafts = draftsOf(list, null);
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void load();
    api.sources().then(
      (s) => (sources = s),
      () => undefined,
    );
  });

  /** An app file chosen: a new app goes to its install page, the next version of one you have
   *  to its page (which offers to deploy it). */
  async function addFile(file: File | undefined): Promise<void> {
    if (!file) return;
    error = null;
    installing = true;
    try {
      const { app, added } = await api.addApp(file);
      navigate(added ? { view: "install-app", name: app.name } : { view: "apps", app: app.name });
    } catch (e) {
      error = (e as Error).message;
    } finally {
      installing = false;
      if (picker) picker.value = "";
    }
  }

  async function draftAction(doing: () => Promise<unknown>): Promise<void> {
    error = null;
    let failed: string | null = null;
    try {
      await doing();
    } catch (e) {
      failed = (e as Error).message;
    }
    await load();
    if (failed) error = failed;
  }

  const newVersion = (app: App): boolean => !app.source.error && !!app.current && !!app.source.version && app.source.version !== app.current.version;
</script>

<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full {LIBRARY_WIDTH} space-y-6 px-8 py-6" data-testid="apps-shelf">
    {#if error}<p class="text-sm text-danger" data-testid="apps-error">{error}</p>{/if}

    {#if more}
      <SourceShelf kind="app" what="apps">
        {#snippet extra()}
          <li class="flex flex-col gap-3 rounded-xl border border-dashed bg-muted/40 p-4">
            <span class="flex items-center gap-3">
              <span class="flex size-11 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground"><WandSparkles class="size-5" /></span>
              <span class="min-w-0"><span class="block font-semibold">Make your own</span><span class="fact block">with the App creator</span></span>
            </span>
            <p class="text-sm text-muted-foreground">Say what it should do; it writes the app with you. Install it when it is ready.</p>
            <div class="mt-auto flex justify-end">
              <Button size="sm" variant="outline" onclick={() => draftAction(async () => (creatorCard = !(await startDraft())))} data-testid="app-create"><WandSparkles />New app</Button>
            </div>
          </li>
          <li class="flex flex-col gap-3 rounded-xl border border-dashed bg-muted/40 p-4">
            <span class="flex items-center gap-3">
              <span class="flex size-11 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground"><FileUp class="size-5" /></span>
              <span class="min-w-0"><span class="block font-semibold">Install from a file</span><span class="fact block">an app's export, a .zip</span></span>
            </span>
            <p class="text-sm text-muted-foreground">One someone shared with you, or your own; the file of an app you have is its next version.</p>
            <div class="mt-auto flex justify-end">
              <input bind:this={picker} type="file" accept=".zip,application/zip" class="hidden" onchange={(e) => addFile(e.currentTarget.files?.[0])} data-testid="app-file" />
              <Button size="sm" variant="outline" disabled={installing} onclick={() => picker?.click()} data-testid="app-new"><FileUp />Choose a file</Button>
            </div>
          </li>
        {/snippet}
      </SourceShelf>
      {#if creatorCard}
        <HelperCard need="app-creator" onready={() => ((creatorCard = false), void draftAction(() => startDraft()))}>
          {#snippet preview()}
            <div class="grid grid-cols-2 gap-3">
              {#each ["Reading list", "Grocery run"] as t (t)}
                <div class="space-y-2 rounded-lg border bg-background p-3"><p class="text-xs font-medium">{t}</p><p class="h-1.5 w-3/4 rounded bg-muted"></p><p class="h-1.5 w-1/2 rounded bg-muted"></p></div>
              {/each}
            </div>
          {/snippet}
        </HelperCard>
      {/if}
    {:else if !apps}
      <LoadingCards />
    {:else}
      {#if apps.length}
        <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" data-testid="library-apps">
          {#each apps as app (app.name)}
            {@const notGiven = missing(app)}
            <li class="flex flex-wrap items-center gap-3 px-4 py-3" data-testid="library-app">
              <span class="flex size-9 shrink-0 items-center justify-center rounded-lg {app.state === 'failed' ? 'bg-danger/10 text-danger' : 'bg-primary/10 text-primary'}"><AppWindow class="size-4" /></span>
              <a class="min-w-0 flex-1 text-foreground no-underline" href={href({ view: "apps", app: app.name })} data-testid="app-manage">
                <span class="block font-medium hover:underline">{app.name}</span>
                <span class="fact block truncate">{fromSourceWords(app.fromSource, sources) ?? "made by you"} · {app.current ? app.current.version : "not installed"}</span>
              </a>
              {#if notGiven.length}
                <span class="inline-flex items-center gap-1 text-xs text-warn" title={`Not given yet: ${notGiven.join(", ")}`} data-testid="app-needs-missing"><TriangleAlert class="size-3" />Incomplete</span>
                <Button size="sm" variant="outline" href={href({ view: "apps", app: app.name })} data-testid="app-fix">Fix</Button>
              {:else if !app.current}
                <Button size="sm" variant="outline" href={href({ view: "install-app", name: app.name })} data-testid="app-install">Install</Button>
              {:else}
                {#if newVersion(app)}<a class="text-xs text-primary no-underline hover:underline" href={href({ view: "apps", app: app.name })} data-testid="app-update">{app.source.version} to deploy</a>{/if}
                <StatusBadge status={app.state} />
              {/if}
            </li>
          {/each}
        </ul>
      {:else}
        <div class="rounded-[10px] border border-dashed px-6 py-8 text-center text-sm text-muted-foreground" data-testid="apps-none">
          <p>No app yet: an app works for you, with its own screen, and its agent thinks when it needs to.</p>
          <Button size="sm" class="mt-3" href={href({ view: "library", shelf: "apps", more: true })} data-testid="apps-get">Get an app</Button>
        </div>
      {/if}

      {#if drafts.length}
        <section class="space-y-2">
          <h2 class="text-sm font-medium text-muted-foreground">Being written, with the App creator</h2>
          <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
            {#each drafts as d (d.id)}
              <li class="flex flex-wrap items-center gap-3 px-4 py-3" data-testid="new-app-draft">
                <FilePenLine class="size-4 text-primary" />
                <span class="min-w-0 flex-1 truncate font-medium">{d.title ?? "a new app"}</span>
                <Button size="sm" variant="ghost" onclick={() => draftAction(() => throwAway(d))} data-testid="draft-throw">Throw away</Button>
                <Button size="sm" variant="outline" onclick={() => continueDraft(d)} data-testid="draft-continue">Continue</Button>
                <Button size="sm" onclick={() => draftAction(() => useDraft(d.id))} data-testid="draft-use">Install it</Button>
              </li>
            {/each}
          </ul>
        </section>
      {/if}
    {/if}
  </div>
</div>
