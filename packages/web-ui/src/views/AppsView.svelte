<script lang="ts">
  // Apps (contract H, apps design; E6: a launcher, not Library), where you open your apps: a big
  // neutral icon and the name each, a click opening the app in a new tab once installed and given
  // all it needs; else to Install, or to its page (AppView, the need not given highlighted). Its
  // news on its corner (its unread inbox messages, lib/apps.ts `news`); what is wrong with it
  // (amber: not given all it needs, broken) on the other. Its ⋯ on hover: Open, Pin to the menu
  // (the menu's Pinned, D.28), Manage in Library (its page). No description nor version here:
  // those are Library's, where apps are got and managed. With no app yet, the empty launcher
  // (dashed slots, No app yet, Find apps in Library), and with no model, its Connect.
  import AppWindow from "@lucide/svelte/icons/app-window";
  import Download from "@lucide/svelte/icons/download";
  import Ellipsis from "@lucide/svelte/icons/ellipsis";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import Library from "@lucide/svelte/icons/library-big";
  import Pin from "@lucide/svelte/icons/pin";
  import PinOff from "@lucide/svelte/icons/pin-off";
  import Settings from "@lucide/svelte/icons/settings";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import DisabledReason from "../components/DisabledReason.svelte";
  import LoadingCards from "../components/LoadingCards.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import Popover from "../components/Popover.svelte";
  import { Button } from "$lib/components/ui/button";
  import { appTitle, missing, news } from "../lib/apps";
  import { onChange } from "../lib/events.svelte";
  import { api } from "../lib/api";
  import { NO_MODEL } from "../lib/blocked";
  import { inbox } from "../lib/inbox.svelte";
  import { emptyFor } from "../lib/menu";
  import { menuUse } from "../lib/menuuse.svelte";
  import type { App } from "../lib/contracts.gen";
  import { pins } from "../lib/pins.svelte";
  import { href, navigate } from "../lib/router.svelte";

  let apps = $state<App[] | null>(null);
  let error = $state<string | null>(null);

  async function load(): Promise<void> {
    try {
      apps = await api.apps();
      error = null;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    const stop = onChange(["apps"], () => void load());
    void load();
    return stop;
  });

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

  const counts = $derived(news(inbox.messages));
  let menuOpen = $state<string | null>(null); // the app whose ⋯ is open

  /** What a click on it does: open it; else install it, or give it what it needs (its page). */
  function go(app: App): void {
    if (!app.current) navigate({ view: "install-app", name: app.name });
    else if (missing(app).length) navigate({ view: "apps", app: app.name, tab: "settings" });
    else void open(app);
  }

  function opened(app: App, open: boolean): void {
    if (open) menuOpen = app.name;
    else if (menuOpen === app.name) menuOpen = null;
  }

  async function pin(app: App): Promise<void> {
    try {
      await pins.toggle("app", app.name);
    } catch {
      /* pins.error says why */
    }
  }

  const empty = $derived(emptyFor({ known: menuUse.modelKnown, ready: menuUse.modelReady }));
  const getApps = href({ view: "library", shelf: "apps", more: true });
</script>

<PageHeader title="Apps" width="max-w-[944px]">
  {#snippet sub()}
    <span class="text-[13.5px]" data-testid="apps-lead"
      >Your apps. Click one to open it.{#if apps?.length}{" "}To get more or change them: <a class="text-link hover:underline" href={getApps} data-testid="apps-get">Library</a>.{/if}</span
    >
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-[944px] space-y-8 px-8 py-4">
    {#if error}<p class="text-sm text-danger" data-testid="apps-error">{error}</p>{/if}

    {#if !apps}
      <div class="flex gap-[26px] pt-4"><LoadingCards count={3} height="size-[88px] mx-5" /></div>
    {:else if !apps.length}
      <!-- the empty launcher (E6): where the apps will sit, and one way to get some -->
      <div data-testid="apps-intro">
        <div class="flex gap-[26px] pt-4" aria-hidden="true">
          {#each [0, 1, 2] as i (i)}
            <div class="flex w-32 flex-col items-center gap-2.5">
              <span class="size-[88px] rounded-[22px] border-2 border-dashed border-border"></span>
              <span class="h-2.5 w-[60px] rounded bg-muted"></span>
            </div>
          {/each}
        </div>
        <h2 class="mt-9 text-[15px] font-semibold">No app yet</h2>
        <p class="mt-1 text-sm text-muted-foreground">Apps are small tools with an agent inside: a planner, a journal. Get them in Library, from Handler and the community.</p>
        <div class="mt-3.5 flex flex-wrap items-center gap-2.5">
          <Button href={getApps} data-testid="apps-get"><Library />Find apps in Library</Button>
          <span class="text-sm text-muted-foreground">or <a class="text-link hover:underline" href={getApps} data-testid="apps-make">make your own</a> with the App creator</span>
        </div>
        {#if empty === "no-model"}<p class="mt-4"><DisabledReason blocked={NO_MODEL} testid="apps-connect" /></p>{/if}
      </div>
    {:else}
      <!-- the launcher: an icon and a name each, a click opens it -->
      <ul class="grid grid-cols-[repeat(auto-fill,128px)] gap-x-[26px] gap-y-7 pt-4" data-testid="apps-yours">
        {#each apps as app (app.name)}
          {@const notGiven = missing(app)}
          {@const failed = !!app.current && !notGiven.length && app.state === "failed"}
          {@const count = counts[app.name] ?? 0}
          {@const pinned = pins.has("app", app.name)}
          {@const what = !app.current ? "Install" : notGiven.length ? "Give it what it needs" : "Open"}
          <li class="enter group relative flex w-32 flex-col items-center" data-testid="app-card">
            <button
              type="button"
              class="flex w-full cursor-pointer flex-col items-center gap-2.5 outline-none"
              title={!app.current
                ? `${appTitle(app)} is not installed: install it`
                : notGiven.length
                  ? `Not given yet: ${notGiven.join(", ")}`
                  : `Open ${appTitle(app)} in a new tab`}
              onclick={() => go(app)}
              data-testid={!app.current ? "app-install" : notGiven.length ? "app-give" : "app-open"}
            >
              <span
                class="flex size-[88px] items-center justify-center rounded-[22px] border bg-card shadow-panel transition-[translate,box-shadow] group-hover:-translate-y-px group-hover:shadow-lift group-has-focus-visible:ring-3 group-has-focus-visible:ring-ring {menuOpen ===
                app.name
                  ? 'ring-3 ring-primary/25'
                  : ''} {app.current ? 'text-muted-foreground' : 'text-muted-foreground/50'}"
                ><AppWindow class="size-9" strokeWidth={1.6} /></span
              >
              <span class="max-w-full truncate text-sm font-[560] text-foreground">{appTitle(app)}</span>
            </button>
            <!-- its news: the accent, not amber (no risk) -->
            {#if count}
              <span
                class="pointer-events-none absolute -top-1.5 left-[92px] min-w-5 rounded-full bg-primary px-[7px] py-px text-center text-[11.5px] font-[650] text-primary-foreground tabular-nums"
                aria-label="{count} new"
                data-testid="app-news">{count}</span
              >
            {/if}
            <!-- what keeps it from opening: amber (a risk); not installed: said in grey -->
            {#if !app.current}
              <span class="pointer-events-none absolute top-[62px] left-3 flex size-[26px] items-center justify-center rounded-lg bg-card text-muted-foreground shadow-panel" title="Not installed" data-testid="app-not-installed"
                ><Download class="size-3.5" /></span
              >
            {:else if notGiven.length}
              <span class="absolute top-[62px] left-3 flex size-[26px] items-center justify-center rounded-lg bg-card text-warn shadow-panel" title={`Not given yet: ${notGiven.join(", ")}`} data-testid="app-needs-missing"
                ><TriangleAlert class="size-3.5" /><span class="sr-only">Incomplete</span></span
              >
            {:else if failed}
              <span class="absolute top-[62px] left-3 flex size-[26px] items-center justify-center rounded-lg bg-card text-warn shadow-panel" title={app.error ?? "Broken"} data-testid="app-failed"
                ><TriangleAlert class="size-3.5" /><span class="sr-only">Broken</span></span
              >
            {/if}
            <div class="absolute top-[62px] right-3 z-10 {menuOpen === app.name ? '' : 'opacity-0 group-hover:opacity-100 group-has-focus-visible:opacity-100'}">
              <Popover bind:open={() => menuOpen === app.name, (v) => opened(app, v)} label="{appTitle(app)}: more" width="14.5rem" testid="app-menu">
                {#snippet trigger(props)}
                  <button
                    type="button"
                    class="flex size-[26px] cursor-pointer items-center justify-center rounded-lg bg-card text-muted-foreground shadow-panel outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                    {...props}
                    aria-label="{appTitle(app)}: more"
                    title="More"
                    data-testid="app-more"><Ellipsis class="size-4" /></button
                  >
                {/snippet}
                {#snippet children(close)}
                  <button type="button" class="menu-item" onclick={() => (close(), go(app))} data-testid="app-menu-open"
                    >{#if what === "Open"}<ExternalLink />{:else if what === "Install"}<Download />{:else}<TriangleAlert />{/if}{what}</button
                  >
                  <button type="button" class="menu-item" onclick={() => (close(), void pin(app))} data-testid="app-pin"
                    >{#if pinned}<PinOff />Unpin from the menu{:else}<Pin />Pin to the menu{/if}</button
                  >
                  <div class="my-1 border-t"></div>
                  <a class="menu-item no-underline" href={href({ view: "apps", app: app.name, tab: "settings" })} onclick={close} data-testid="app-manage"><Settings />Manage in Library</a>
                {/snippet}
              </Popover>
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</div>
