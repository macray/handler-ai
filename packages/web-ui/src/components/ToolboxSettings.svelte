<script lang="ts">
  // The toolbox (contract B.7), in Settings → Sandboxes: the system every agent works in, which Handler
  // generates from its base, the system packages turned on here and the user's own lines. Each
  // system package says what it gives and who needs it; what is needed from the toolbox says what
  // gives it (amber when nothing does). Changes are saved at once and used once applied: Apply
  // builds the toolbox with the build cache, Update the system pulls and builds it all again; both
  // then rebuild and check every image on it (D.4). The generated Containerfile is shown folded.
  import Box from "@lucide/svelte/icons/box";
  import Pencil from "@lucide/svelte/icons/pencil";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { api } from "../lib/api";
  import type { HarnessInfo, SystemPackageInfo, ToolboxInfo } from "../lib/contracts.gen";
  import ToolboxEditor from "./ToolboxEditor.svelte";
  import When from "./When.svelte";

  // a daemon's abilities (A.8), as the agent editor names the sandboxes having them
  const ABILITY_WORDS: Record<string, string> = {
    nested: "run containers",
    privileged: "are privileged",
    display: "show windows",
  };

  let {
    toolbox,
    harnesses,
    disabled,
    onchanged,
    onbuild,
  }: {
    toolbox: ToolboxInfo;
    harnesses: HarnessInfo[];
    disabled: boolean; // a build runs, or a request of the page's
    onchanged: () => void; // what it is made of changed: load it again
    onbuild: (update: boolean) => void;
  } = $props();

  let offered = $state<SystemPackageInfo[]>([]);
  let agents = $state<Record<string, string>>({}); // id → name, to say who needs what
  let editing = $state(false); // the user's lines are being edited
  let generated = $state<string | null>(null); // the generated Containerfile, once unfolded
  let busy = $state(false);
  let error = $state<string | null>(null);

  $effect(() => {
    api.systemPackages().then(
      (list) => (offered = list),
      (e: Error) => (error = e.message),
    );
    api.agents().then(
      (list) => (agents = Object.fromEntries(list.map((a) => [a.id, a.name ?? a.scope ?? a.id]))),
      () => {},
    );
  });

  const packagesOn = $derived(toolbox.systemPackages ?? []);
  const needs = $derived(toolbox.needs ?? []);
  const on = $derived(packagesOn.map((p) => p.name));
  const pending = $derived(toolbox.imagePresent && packagesOn.some((p) => p.builtVersion !== p.version));
  const lacking = $derived(needs.filter((n) => !n.providedBy));

  // who needs something, in words: Handler, an agent program by its name, a tool, an agent by
  // its name
  function who(entries: string[]): string {
    return entries
      .map((entry) => {
        const [kind, name] = [entry.split(":")[0], entry.slice(entry.indexOf(":") + 1)];
        if (kind === "handler") return "Handler";
        if (kind === "harness") return harnesses.find((h) => h.name === name)?.product ?? name;
        if (kind === "agent") return `agent ${agents[name] ?? name}`;
        if (kind === "addon") return `the ${name} tool`;
        return name;
      })
      .join(", ");
  }

  function givenBy(provider: string | null | undefined): string {
    if (!provider) return "nothing gives it";
    if (provider === "base") return "Handler's base";
    if (provider === "lines") return "your lines";
    return provider.replace("system-package:", "");
  }

  async function toggle(p: SystemPackageInfo, wanted: boolean): Promise<void> {
    if (
      wanted &&
      !confirm(
        `Turn on ${p.name}? Its install script runs as root when the toolbox is built, and every agent gets what it installs. It is used once you apply it.`,
      )
    )
      return;
    busy = true;
    error = null;
    try {
      await api.setSystemPackages(wanted ? [...on, p.name] : on.filter((n) => n !== p.name));
      changed();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  function build(update: boolean): void {
    const question = update
      ? "Update the toolbox's system? Everything is downloaded and built again (a large download), then every agent program and tool image already built is rebuilt on it and checked; they are used only if all pass."
      : "Apply your changes to the toolbox? It is built again from the first change, then every agent program and tool image already built is rebuilt on it and checked; they are used only if all pass.";
    if (confirm(question)) onbuild(update);
  }

  function loadGenerated(): void {
    api.toolboxContainerfile().then(
      (file) => (generated = file.content),
      (err: Error) => (generated = `cannot be generated: ${err.message}`),
    );
  }

  function unfold(e: Event): void {
    if ((e.currentTarget as HTMLDetailsElement).open && generated === null) loadGenerated();
  }

  // what it is made of changed: the generated Containerfile too, when it is shown
  function changed(): void {
    if (generated !== null) loadGenerated();
    onchanged();
  }
</script>

<div class="space-y-4" data-testid="toolbox">
  <div class="space-y-1">
    <h2 class="text-base font-semibold">Toolbox</h2>
    <p class="max-w-2xl text-sm text-muted-foreground">
      The system every agent works in: Handler's base, the system packages you turn on, and your own lines. Changes are used once applied: the toolbox is
      built again, then every image on it, each checked before any is used.
    </p>
  </div>
  {#if toolbox.problem}<p class="text-sm text-danger" data-testid="toolbox-problem">{toolbox.problem}</p>{/if}
  {#if error}<p class="text-sm text-danger" data-testid="toolbox-error">{error}</p>{/if}
  {#if lacking.length}
    <div class="space-y-1 rounded-[10px] border border-warn/40 bg-warn/5 px-4 py-3 text-sm text-warn" data-testid="toolbox-lacking">
      {#each lacking as n (n.commands.join())}
        <p class="flex items-start gap-1.5">
          <TriangleAlert class="mt-0.5 size-3.5 shrink-0" />
          <span><span class="font-mono">{n.commands.join(" or ")}</span>: nothing in the toolbox gives it, needed by {who(n.neededBy)}.</span>
        </p>
      {/each}
    </div>
  {/if}

  <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
    <li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5">
      <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:flex"><Box class="size-4" /></span>
      <div class="min-w-0 flex-1 basis-60 space-y-0.5">
        <p class="flex flex-wrap items-center gap-2">
          <span class="font-medium">toolbox</span>
          {#if !toolbox.imagePresent}
            <span class="inline-flex items-center gap-1 rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn"><TriangleAlert class="size-3" />not built yet</span>
          {:else if pending}
            <span class="rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn" data-testid="toolbox-pending">changes not applied</span>
          {/if}
        </p>
        <p class="fact truncate">{toolbox.distro ?? "?"}&ensp;·&ensp;{toolbox.image}{#if toolbox.builtAt}&ensp;·&ensp;built <When at={toolbox.builtAt} />{/if}</p>
        <p class="fact truncate" data-testid="toolbox-directory">yours: {toolbox.directory}</p>
      </div>
      <div class="ml-auto flex gap-1.5">
        <Button size="sm" variant="ghost" disabled={disabled} onclick={() => build(true)} data-testid="toolbox-update"><RefreshCw />Update the system</Button>
        <Button size="sm" variant={pending ? "default" : "outline"} disabled={disabled || !!toolbox.problem} onclick={() => build(false)} data-testid="toolbox-apply"
          >Apply</Button
        >
      </div>
    </li>
  </ul>

  <div class="space-y-2">
    <p class="section-label">system packages</p>
    <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel" data-testid="system-packages">
      {#each offered as p (p.name)}
        {@const chosen = packagesOn.find((x) => x.name === p.name)}
        <li class="flex items-start gap-3 px-4 py-3" data-testid="system-package">
          <Checkbox
            class="mt-0.5"
            checked={!!chosen}
            disabled={busy || disabled || !!p.error}
            onCheckedChange={(v) => toggle(p, v === true)}
            aria-label={p.name}
            data-testid="system-package-toggle"
          />
          <div class="min-w-0 flex-1 space-y-0.5">
            <p class="flex flex-wrap items-baseline gap-x-2">
              <span class="font-medium" data-testid="system-package-name">{p.name}</span>
              {#if !p.builtin}<span class="text-xs text-muted-foreground">{p.overridesBuiltin ? "yours, in place of Handler's" : "yours"}</span>{/if}
              {#if chosen && toolbox.imagePresent && chosen.builtVersion !== chosen.version}
                <span class="rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn">not applied yet</span>
              {/if}
            </p>
            {#if p.error}
              <p class="text-xs text-danger">{p.error}</p>
            {:else}
              <p class="text-xs text-muted-foreground">{p.description}</p>
              <p class="fact">gives {p.provides?.join(", ")}</p>
              {#each p.daemons ?? [] as daemon (daemon.command)}
                <p class="text-xs text-muted-foreground" data-testid="system-package-daemon">
                  starts <span class="font-mono">{daemon.command}</span> in the sandboxes of agents that {daemon.abilities.map((a) => ABILITY_WORDS[a]).join(" or ")}
                </p>
              {/each}
              {#if chosen?.neededBy?.length}
                <p class="text-xs" data-testid="system-package-needed-by">needed by {who(chosen.neededBy)}</p>
              {:else if chosen}
                <p class="text-xs text-muted-foreground">nothing needs it now</p>
              {/if}
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  </div>

  <details class="group text-sm" data-testid="toolbox-needs">
    <summary class="cursor-pointer text-muted-foreground hover:text-foreground">What Handler and your agents need from it ({needs.length})</summary>
    <ul class="mt-2 divide-y overflow-hidden rounded-[10px] border bg-card shadow-panel">
      {#each needs as n (n.commands.join())}
        <li class="flex flex-wrap items-baseline gap-x-3 px-4 py-2">
          <span class="font-mono text-xs">{n.commands.join(" or ")}</span>
          <span class="text-xs text-muted-foreground">{who(n.neededBy)}</span>
          <span class="ml-auto text-xs {n.providedBy ? 'text-muted-foreground' : 'text-warn'}">{givenBy(n.providedBy)}</span>
        </li>
      {/each}
    </ul>
  </details>

  <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
    <li class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
      <div class="min-w-0 flex-1 space-y-0.5">
        <p class="font-medium">Your lines</p>
        <p class="text-xs text-muted-foreground">Containerfile lines added last, for what no system package gives.</p>
      </div>
      <Button size="sm" variant="ghost" disabled={editing} onclick={() => (editing = true)} data-testid="toolbox-edit"><Pencil />Edit</Button>
    </li>
  </ul>
  {#if editing}
    <ToolboxEditor directory={toolbox.directory} onclose={() => (editing = false)} onsaved={changed} />
  {/if}

  <details class="text-sm" ontoggle={unfold} data-testid="toolbox-containerfile">
    <summary class="cursor-pointer text-muted-foreground hover:text-foreground">The Containerfile Handler generates (read-only)</summary>
    <pre class="term-surface mt-2 max-h-96 overflow-auto rounded-md border p-3 font-mono text-xs whitespace-pre-wrap">{generated ?? "…"}</pre>
  </details>
</div>
