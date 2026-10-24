<script lang="ts">
  // Apps (contract H, docs/dev/design/apps.md): what works for you. Yours as cards, Chat
  // first (Handler's own, always there: ChatView), then the apps (each opens its page,
  // AppView; Open once deployed), the drafts of new apps waiting (H.15), then what the sources
  // offer (D.26: Handler's first; a new version of one you have, then those you have not; the
  // first few, the rest in Discover), making
  // your own with the App creator (on a draft kept by Handler,
  // lib/drafts.ts) and installing an app file (an export: a new app, or the next version of one
  // you have). Installing goes through its install page (AppInstallView). With no app yet, the
  // page says what an app is first.
  import AppWindow from "@lucide/svelte/icons/app-window";
  import Bot from "@lucide/svelte/icons/bot";
  import CalendarClock from "@lucide/svelte/icons/calendar-clock";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import FilePenLine from "@lucide/svelte/icons/file-pen-line";
  import FileUp from "@lucide/svelte/icons/file-up";
  import WandSparkles from "@lucide/svelte/icons/wand-sparkles";
  import MessagesSquare from "@lucide/svelte/icons/messages-square";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Upload from "@lucide/svelte/icons/upload";
  import LoadingCards from "../components/LoadingCards.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import StatusBadge from "../components/StatusBadge.svelte";
  import { Button } from "$lib/components/ui/button";
  import { missing } from "../lib/apps";
  import { api } from "../lib/api";
  import type { App, Session, Source, SourceItem } from "../lib/contracts.gen";
  import { continueDraft, draftsOf, startDraft, throwAway, useDraft } from "../lib/drafts";
  import { href, navigate } from "../lib/router.svelte";
  import { fromSourceWords, fromWords, offered } from "../lib/sources";

  let apps = $state<App[] | null>(null);
  let sources = $state<Source[]>([]);
  let error = $state<string | null>(null);
  let installing = $state<string | null>(null);
  let picker = $state<HTMLInputElement>(); // the app file to install
  let drafts = $state<Session[]>([]); // of new apps, with the App creator

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

  async function loadSources(): Promise<void> {
    try {
      sources = await api.sources();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void load();
    void loadSources(); // once: a source is read again at most daily, or from Settings → Sources
    const timer = setInterval(load, 5000); // started and stopped backends (idle timeout)
    return () => clearInterval(timer);
  });

  const fromSources = $derived(offered(sources, "app"));
  const updates = $derived(fromSources.filter((o) => o.item.update));
  const toInstall = $derived(fromSources.filter((o) => !o.item.installed));
  const unread = $derived(sources.filter((s) => s.error && !s.commit)); // never read: nothing offered
  const SHORT = 3; // the rest in Discover

  /** An app file chosen: a new app goes to its install page (what it needs, on one page), the
   *  next version of one you have to its page (which offers to deploy it). */
  async function addFile(file: File | undefined): Promise<void> {
    if (!file) return;
    error = null;
    installing = file.name;
    try {
      const { app, added } = await api.addApp(file);
      navigate(added ? { view: "install-app", name: app.name } : { view: "apps", app: app.name });
    } catch (e) {
      error = (e as Error).message;
    } finally {
      installing = null;
      if (picker) picker.value = "";
    }
  }

  /** Its code taken from its source: a new app goes to its install page, the next version of one
   *  you have to its page (which offers to deploy it). */
  async function take(source: Source, item: SourceItem): Promise<void> {
    installing = item.name;
    error = null;
    try {
      const { app, added } = await api.appFromSource(source.id, item.name);
      navigate(added ? { view: "install-app", name: app.name } : { view: "apps", app: app.name });
    } catch (e) {
      error = (e as Error).message;
    } finally {
      installing = null;
    }
  }

  async function open(app: App): Promise<void> {
    // opened now, while the click still counts as a user action (popup blockers), filled after
    const tab = window.open("about:blank", "_blank");
    try {
      const link = await api.openApp(app.name);
      if (tab) {
        tab.opener = null;
        tab.location.href = link.url;
      }
    } catch (e) {
      tab?.close();
      error = (e as Error).message;
    }
  }

  async function draftAction(doing: () => Promise<unknown>): Promise<void> {
    error = null;
    try {
      await doing();
    } catch (e) {
      error = (e as Error).message;
    }
    await load();
  }

  const newVersion = (app: App): boolean => !app.source.error && !!app.current && !!app.source.version && app.source.version !== app.current.version;
</script>

<PageHeader titled title="Apps" />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-5xl space-y-10 px-8 py-10">
    {#if apps && !apps.length}
      <div class="space-y-5" data-testid="apps-intro">
        <PageTitle
          title="Apps"
          description="An app works for you, in its own sandbox, with your models. Installing one is choosing what it may touch: its agents are set up for it."
        />
        <div class="grid gap-3 sm:grid-cols-3">
          <div class="rounded-xl bg-muted/70 px-4 py-3.5">
            <p class="flex items-center gap-2 font-medium"><AppWindow class="size-4" />Open it</p>
            <p class="mt-1 text-sm text-muted-foreground">Its screen, here or on your phone.</p>
          </div>
          <div class="rounded-xl bg-muted/70 px-4 py-3.5">
            <p class="flex items-center gap-2 font-medium"><Bot class="size-4" />Its agent thinks</p>
            <p class="mt-1 text-sm text-muted-foreground">When it needs judgment, its agent does it, on the model you choose.</p>
          </div>
          <div class="rounded-xl bg-muted/70 px-4 py-3.5">
            <p class="flex items-center gap-2 font-medium"><CalendarClock class="size-4" />It runs by itself</p>
            <p class="mt-1 text-sm text-muted-foreground">When you turn it on, and tells you in your Inbox.</p>
          </div>
        </div>
      </div>
    {:else}
      <PageTitle title="Apps" description="What works for you: you open it, ask it, or it runs by itself. Each one touches only what you gave it." />
    {/if}
    {#if error}<p class="text-sm text-danger" data-testid="apps-error">{error}</p>{/if}

    {#if !apps}
      <div class="grid gap-4 sm:grid-cols-3"><LoadingCards count={3} height="h-36" /></div>
    {:else}
      <section class="space-y-3">
        <h2 class="flex items-baseline gap-2 font-semibold">Yours <span class="fact">{apps.length + 1}</span></h2>
        <ul class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <li class="enter flex flex-col gap-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="chat-card">
            <a class="flex items-center gap-3 text-foreground no-underline" href={href({ view: "chat" })}>
              <span class="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><MessagesSquare class="size-5" /></span>
              <span class="min-w-0">
                <span class="block truncate font-semibold">Chat</span>
                <span class="fact block">from Handler · always there</span>
              </span>
            </a>
            <p class="text-sm text-muted-foreground">Talk about anything, with no folder of yours: with Claude, Codex or the model alone.</p>
            <div class="mt-auto flex justify-end"><Button size="sm" variant="outline" href={href({ view: "chat" })} data-testid="chat-open">Open</Button></div>
          </li>
          {#each apps as app (app.name)}
            {@const notGiven = missing(app)}
            <li class="enter flex flex-col gap-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="app-card">
              <a class="flex items-center gap-3 text-foreground no-underline" href={href({ view: "apps", app: app.name })} data-testid="app-manage">
                <span class="flex size-11 shrink-0 items-center justify-center rounded-xl {app.state === 'failed' ? 'bg-danger/10 text-danger' : 'bg-primary/10 text-primary'}"
                  ><AppWindow class="size-5" /></span
                >
                <span class="min-w-0">
                  <span class="block truncate font-semibold">{app.name}</span>
                  <span class="fact block">{fromSourceWords(app.fromSource, sources) ?? "made by you"} · {app.current ? app.current.version : "not installed"}</span>
                </span>
              </a>
              {#if app.description ?? app.source.description}<p class="text-sm text-muted-foreground">{app.description ?? app.source.description}</p>{/if}
              <div class="mt-auto flex flex-wrap items-center gap-2">
                {#if app.current}<StatusBadge status={app.state} />{/if}
                {#if notGiven.length}
                  <span class="inline-flex items-center gap-1 rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn" title={`Not given yet: ${notGiven.join(", ")}`} data-testid="app-needs-missing"
                    ><TriangleAlert class="size-3" />{notGiven.length === 1 ? "needs one more thing" : `needs ${notGiven.length} more things`}</span
                  >
                {:else if newVersion(app)}
                  <span class="rounded-md bg-primary/10 px-1.5 py-0.5 text-xs text-primary">{app.source.version} to deploy</span>
                {/if}
                <span class="ml-auto">
                  {#if !app.current}
                    <Button size="sm" variant="outline" href={href({ view: "install-app", name: app.name })} data-testid="app-install"><Upload />Install</Button>
                  {:else}
                    <Button size="sm" variant="outline" onclick={() => open(app)} data-testid="app-open"><ExternalLink />Open</Button>
                  {/if}
                </span>
              </div>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    {#if drafts.length}
      <section class="space-y-3">
        <h2 class="flex items-baseline gap-2 font-semibold">Being written <span class="text-xs font-normal text-muted-foreground">new apps, with the App creator</span></h2>
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

    {#if apps}
      <section class="space-y-3">
        <h2 class="flex items-baseline gap-3 font-semibold">{apps.length ? "Get more" : "Start with one"}
          <a class="text-sm font-normal" href={href({ view: "discover" })} data-testid="apps-discover">See all in Discover{updates.length + toInstall.length > SHORT ? ` (${updates.length + toInstall.length})` : ""}</a></h2>
        {#each unread as s (s.id)}
          <p class="text-sm text-muted-foreground" title={s.error ?? undefined} data-testid="source-unread">
            {s.official ? "Handler's apps" : `The apps of ${s.name ?? s.id}`} cannot be read now: <a href={href({ view: "settings", section: "sources" })}>Settings → Sources</a>
          </p>
        {/each}
        <ul class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {#each [...updates, ...toInstall].slice(0, SHORT) as { source, item } (`${source.id}/${item.name}`)}
            <li class="flex flex-col gap-3 rounded-xl border bg-card p-4 shadow-panel" data-testid="source-app">
              <div class="flex items-center gap-3">
                <span class="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><AppWindow class="size-5" /></span>
                <span class="min-w-0">
                  <span class="block truncate font-semibold">{item.name}</span>
                  <span class="fact block">{fromWords(source)} · {item.version}</span>
                </span>
              </div>
              {#if item.description}<p class="text-sm text-muted-foreground">{item.description}</p>{/if}
              <div class="mt-auto flex items-center justify-end gap-2">
                {#if item.update}
                  <span class="mr-auto rounded-md bg-primary/10 px-1.5 py-0.5 text-xs text-primary">a new version of yours</span>
                  <Button size="sm" variant="outline" disabled={!!installing} onclick={() => take(source, item)} data-testid="source-app-update">Get it</Button>
                {:else}
                  <Button size="sm" disabled={!!installing} onclick={() => take(source, item)} data-testid="source-app-install">Install</Button>
                {/if}
              </div>
            </li>
          {/each}
          <li class="flex flex-col gap-3 rounded-xl border border-dashed bg-muted/40 p-4">
            <div class="flex items-center gap-3">
              <span class="flex size-11 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground"><WandSparkles class="size-5" /></span>
              <span class="min-w-0">
                <span class="block font-semibold">Make your own</span>
                <span class="fact block">with the App creator</span>
              </span>
            </div>
            <p class="text-sm text-muted-foreground">Say what it should do; it writes the app with you, on a draft Handler keeps. Install it when it is ready.</p>
            <div class="mt-auto flex justify-end">
              <Button size="sm" variant="outline" onclick={() => draftAction(() => startDraft())} data-testid="app-create"><WandSparkles />New app</Button>
            </div>
          </li>
          <li class="flex flex-col gap-3 rounded-xl border border-dashed bg-muted/40 p-4">
            <div class="flex items-center gap-3">
              <span class="flex size-11 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground"><FileUp class="size-5" /></span>
              <span class="min-w-0">
                <span class="block font-semibold">Install from a file</span>
                <span class="fact block">an app's export, a .zip</span>
              </span>
            </div>
            <p class="text-sm text-muted-foreground">One someone shared with you, or your own. Handler keeps its own copy; the file of an app you have is its next version.</p>
            <div class="mt-auto flex flex-wrap justify-end gap-2">
              <input bind:this={picker} type="file" accept=".zip,application/zip" class="hidden" onchange={(e) => addFile(e.currentTarget.files?.[0])} data-testid="app-file" />
              <Button size="sm" variant="outline" disabled={!!installing} onclick={() => picker?.click()} data-testid="app-new"><FileUp />Choose a file</Button>
            </div>
          </li>
        </ul>
      </section>
    {/if}
  </div>
</div>
