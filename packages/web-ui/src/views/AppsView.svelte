<script lang="ts">
  // Apps (contract H, apps design), the place where you open your apps: a card each, the whole
  // card opening the app in a new tab once installed and given all it needs; else to Install, or
  // to its page (AppView, the need not given highlighted). In its corner on hover, its page (the
  // gear: its settings) and its pin (the menu's Pinned, D.28; kept in sight when on). Getting and
  // managing them is the Library's Apps shelf (Get apps). With no app yet, what an app is, and Get an app.
  import AppWindow from "@lucide/svelte/icons/app-window";
  import ArrowUpRight from "@lucide/svelte/icons/arrow-up-right";
  import Bot from "@lucide/svelte/icons/bot";
  import CalendarClock from "@lucide/svelte/icons/calendar-clock";
  import Download from "@lucide/svelte/icons/download";
  import Settings from "@lucide/svelte/icons/settings";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import LoadingCards from "../components/LoadingCards.svelte";
  import PageHeader from "../components/PageHeader.svelte";
  import PinButton from "../components/PinButton.svelte";
  import { Button, buttonVariants } from "$lib/components/ui/button";
  import { missing } from "../lib/apps";
  import { api } from "../lib/api";
  import type { App } from "../lib/contracts.gen";
  import { pins } from "../lib/pins.svelte";
  import { href } from "../lib/router.svelte";

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
    void load();
    const timer = setInterval(load, 5000); // started and stopped backends (idle timeout)
    return () => clearInterval(timer);
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

  const getApps = href({ view: "library", shelf: "apps", more: true });
</script>

<PageHeader title="Apps" width="max-w-[944px]">
  {#snippet actions()}
    {#if apps?.length}<Button size="sm" variant="outline" class="ml-auto" href={getApps} data-testid="apps-get"><Download />Get apps</Button>{/if}
  {/snippet}
</PageHeader>
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-[944px] space-y-8 px-8 py-4">
    {#if error}<p class="text-sm text-danger" data-testid="apps-error">{error}</p>{/if}

    {#if !apps}
      <div class="grid gap-4 sm:grid-cols-2"><LoadingCards count={2} height="h-[84px]" /></div>
    {:else if !apps.length}
      <div class="space-y-5" data-testid="apps-intro">
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
        <Button href={getApps} data-testid="apps-get">Get an app</Button>
      </div>
    {:else}
      <!-- one height and one line each, so the rows line up; the description in full is on its page -->
      <ul class="grid gap-4 sm:grid-cols-2" data-testid="apps-yours">
        {#each apps as app (app.name)}
          {@const notGiven = missing(app)}
          {@const description = app.description ?? app.source.description}
          {@const pinned = pins.has("app", app.name)}
          <li
            class="enter group relative flex h-[84px] items-center gap-3.5 rounded-xl bg-card px-4 shadow-panel transition-[translate,box-shadow] hover:-translate-y-px hover:shadow-lift"
            data-testid="app-card"
          >
            <span
              class="flex size-[42px] shrink-0 items-center justify-center rounded-[11px] {!app.current
                ? 'bg-muted text-muted-foreground'
                : app.state === 'failed'
                  ? 'bg-danger/10 text-danger'
                  : 'bg-primary/10 text-primary'}"><AppWindow class="size-5" /></span
            >
            <span class="min-w-0 flex-1 {app.current ? 'pr-10' : 'pr-24'}">
              <span class="flex items-center gap-2.5">
                <!-- the name stretched over the card: what a click on the card does -->
                {#if !app.current}
                  <a
                    class="truncate font-semibold text-foreground no-underline outline-none after:absolute after:inset-0 after:rounded-xl focus-visible:after:ring-2 focus-visible:after:ring-ring"
                    href={href({ view: "install-app", name: app.name })}
                    data-testid="app-install">{app.name}</a
                  >
                {:else if notGiven.length}
                  <a
                    class="truncate font-semibold text-foreground no-underline outline-none after:absolute after:inset-0 after:rounded-xl focus-visible:after:ring-2 focus-visible:after:ring-ring"
                    href={href({ view: "apps", app: app.name })}
                    title={`Not given yet: ${notGiven.join(", ")}`}
                    data-testid="app-give">{app.name}</a
                  >
                {:else}
                  <button
                    type="button"
                    class="cursor-pointer truncate font-semibold text-foreground outline-none after:absolute after:inset-0 after:rounded-xl focus-visible:after:ring-2 focus-visible:after:ring-ring"
                    title={`Open ${app.name} in a new tab`}
                    onclick={() => open(app)}
                    data-testid="app-open">{app.name}</button
                  >
                {/if}
                <!-- only what needs you, or that it runs: an idle or asleep app says nothing -->
                {#if app.current && notGiven.length}
                  <span class="inline-flex shrink-0 items-center gap-1 text-[12.5px] font-medium text-warn" title={`Not given yet: ${notGiven.join(", ")}`} data-testid="app-needs-missing"
                    ><TriangleAlert class="size-3.5" />Incomplete</span
                  >
                {:else if app.current && app.state === "failed"}
                  <span class="inline-flex shrink-0 items-center gap-1 text-[12.5px] font-medium text-warn" title={app.error ?? undefined} data-testid="app-failed"><TriangleAlert class="size-3.5" />Broken</span>
                {:else if app.current && (app.state === "running" || app.state === "starting")}
                  <span class="inline-flex shrink-0 items-center gap-1.5 text-[12.5px] font-medium text-muted-foreground" data-testid="app-running"
                    ><span class="size-[7px] rounded-full bg-ok ring-3 ring-ok/15"></span>{app.state}</span
                  >
                {/if}
              </span>
              {#if description}<span class="mt-0.5 block truncate text-sm text-muted-foreground" title={description}>{description}</span>{/if}
            </span>
            <span class="absolute top-2 right-2 z-10 flex items-center gap-0.5">
              <Button
                variant="ghost"
                size="icon"
                class="size-8 text-muted-foreground opacity-0 group-hover:opacity-100 group-has-focus-visible:opacity-100"
                href={href({ view: "apps", app: app.name })}
                title="Settings"
                aria-label="{app.name}: settings"
                data-testid="app-manage"><Settings class="size-4" /></Button
              >
              <span class={pinned ? "" : "opacity-0 group-hover:opacity-100 group-has-focus-visible:opacity-100"}><PinButton kind="app" id={app.name} label={app.name} /></span>
            </span>
            {#if !app.current}
              <span class="pointer-events-none absolute right-3 bottom-3 {buttonVariants({ variant: 'outline', size: 'sm' })}" aria-hidden="true"><Download />Install</span>
            {:else if !notGiven.length}
              <ArrowUpRight class="pointer-events-none absolute right-3.5 bottom-3 size-4 text-muted-foreground group-hover:text-primary" aria-hidden="true" />
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</div>
