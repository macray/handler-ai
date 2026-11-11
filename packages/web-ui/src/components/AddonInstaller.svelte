<script lang="ts">
  // Installing an addon (contract G.5): from a source (D.26), a folder or an https:// .tar.gz
  // archive. Nothing is installed before its preview is shown (the hosts its agents may reach,
  // the secrets it asks for, its commands, MCP server, skills, and that its Containerfile runs
  // code when built); the install takes exactly the previewed content (its digest). In a dialog:
  // each source's addons not installed yet (Handler's first, saying where each comes from), a
  // folder or an archive below them, then the preview. Installed, the page goes on to its first
  // configuration (`oninstalled`); updated, it keeps the ones it has.
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { api } from "../lib/api";
  import type { AddonPreview, Source } from "../lib/contracts.gen";
  import { fromWords, offered } from "../lib/sources";
  import Dialog from "./Dialog.svelte";

  let { oninstalled }: { oninstalled: (message: string, addon: string, updated: boolean) => void } = $props();

  let sources = $state<Source[]>([]);
  let source = $state(""); // a folder or an archive URL typed by the user
  let shown = $state(false); // the dialog open
  let preview = $state<AddonPreview | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);

  const available = $derived(offered(sources, "addon").filter((o) => !o.item.installed));
  const unread = $derived(sources.filter((s) => s.error && !s.commit)); // never read: nothing offered

  /** The dialog, on its list. */
  export function open(): void {
    preview = null;
    error = null;
    shown = true;
  }

  async function loadSources(): Promise<void> {
    try {
      sources = await api.sources();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void loadSources();
  });

  /** Show what installing from `at` brings (also an installed addon's update). */
  export async function look(at: string): Promise<void> {
    busy = true;
    error = null;
    try {
      shown = true;
      preview = await api.previewAddon(at);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function install(): Promise<void> {
    if (!preview) return;
    busy = true;
    error = null;
    try {
      const adds = (preview.toolbox?.adds ?? []).map((a) => a.name);
      const updated = preview.replaces === "installed";
      const done = await api.installAddon(preview.source, preview.digest, adds);
      const built =
        done.build?.target === "toolbox"
          ? ` (the toolbox is being rebuilt with ${adds.join(", ")}, then its tools are prepared: Settings → Sandboxes)`
          : done.build
            ? " (its image is being built: Settings → Sandboxes)"
            : "";
      preview = null;
      source = "";
      shown = false;
      await loadSources();
      oninstalled(updated ? `${done.addon.name} updated${built}.` : `${done.addon.name} installed${built}. Next, connect it:`, done.addon.name, updated);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  const replaced: Record<string, string> = {
    builtin: "the built-in tool of that name (yours wins)",
    installed: "the installed one (an update)",
    own: "your own tool of that name: move its folder away first",
  };
</script>

{#snippet fact(label: string, items: string[] | null | undefined, mono = true)}
  <div class="grid gap-1 sm:grid-cols-[10rem_1fr]">
    <dt class="text-muted-foreground">{label}</dt>
    <dd class="{mono ? 'font-mono text-xs leading-5' : ''} break-words">{items?.length ? items.join(", ") : "none"}</dd>
  </div>
{/snippet}

<Dialog
  bind:open={shown}
  title={preview ? `Install ${preview.name}?` : "Install a tool"}
  description={preview ? (preview.description ?? undefined) : "Nothing is installed before you see what it brings."}
  wide={Boolean(preview)}
  testid="addon-installer"
>
  {#if preview}
    <div class="space-y-5" data-testid="addon-preview">
      <p class="fact break-all">{preview.source}</p>
      <dl class="space-y-3 rounded-[10px] border bg-card p-4">
        {@render fact("Its agents reach", preview.egress?.length ? preview.egress : ["no host"])}
        {@render fact("Settings it asks for", preview.settings?.map((x) => x.name))}
        {@render fact("Secrets it asks for", preview.secretSlots?.map((x) => x.name))}
        {@render fact("Programs", preview.commands)}
        {@render fact("MCP server", preview.mcp?.length ? [preview.mcp.join(" ")] : null)}
        {@render fact("Skills", preview.skills)}
        {#if preview.env?.length}{@render fact("Environment", preview.env)}{/if}
      </dl>
      {#if preview.image}
        <p class="flex items-start gap-2.5 rounded-[10px] border border-warn/40 bg-warn/5 p-3 text-warn">
          <TriangleAlert class="mt-0.5 size-4 shrink-0" />
          <span>Its Containerfile runs code on this computer when its image <span class="font-mono text-xs">{preview.image}</span> is built.</span>
        </p>
      {/if}
      {#if preview.toolbox?.has?.length}<p class="text-muted-foreground">From the toolbox it uses <span class="font-mono text-xs">{preview.toolbox.has.join(", ")}</span>.</p>{/if}
      {#if preview.toolbox?.adds?.length}
        <div class="space-y-2 rounded-[10px] border border-warn/40 bg-warn/5 p-3" data-testid="addon-toolbox-adds">
          <p class="flex items-start gap-2.5 text-warn">
            <TriangleAlert class="mt-0.5 size-4 shrink-0" />
            <span>Installing it adds to the toolbox, the system every agent works in, then rebuilds it:</span>
          </p>
          <ul class="space-y-2 pl-6">
            {#each preview.toolbox.adds as add (add.name)}
              <li>
                <span class="font-mono text-xs">{add.name}</span>, for <span class="font-mono text-xs">{(add.provides ?? []).join(", ")}</span>
                <span class="text-muted-foreground">· {add.source ? `from ${add.source.replace(/^source:/, "")}, installed with it` : (add.description ?? "")}</span>
                {#if add.script}
                  <details class="mt-1">
                    <summary class="cursor-pointer text-xs text-muted-foreground">Its install script, run as root while the toolbox is built</summary>
                    <pre class="mt-1 max-h-48 overflow-auto rounded-md bg-muted p-2 font-mono text-xs">{add.script}</pre>
                  </details>
                {/if}
              </li>
            {/each}
          </ul>
        </div>
      {/if}
      {#if preview.toolbox?.lacking?.length}
        <p data-testid="addon-toolbox-lacking">
          It needs <span class="font-mono text-xs">{preview.toolbox.lacking.join(", ")}</span>, which no system package provides: add it to your own lines of the toolbox (Settings → Sandboxes). Until then it is installed, not ready.
        </p>
      {/if}
      {#if preview.replaces}<p>Replaces {replaced[preview.replaces]}.</p>{/if}
      {#if error}<p class="text-danger" data-testid="addon-install-error">{error}</p>{/if}
      <div class="flex flex-wrap items-center gap-2 border-t pt-4">
        <Button variant="ghost" size="sm" onclick={() => (preview = null)}>Back</Button>
        <span class="flex-1"></span>
        <Button size="sm" disabled={busy || preview.replaces === "own"} onclick={install} data-testid="addon-install">{preview.toolbox?.adds?.length ? "Install and add to the toolbox" : "Install"}</Button>
      </div>
    </div>
  {:else}
    <div class="space-y-6">
      <div class="space-y-2">
        <p class="font-medium">From a source</p>
        {#each unread as s (s.id)}
          <p class="text-xs text-muted-foreground" title={s.error ?? undefined}>{s.official ? "Handler's source" : (s.name ?? s.id)} cannot be read now: Settings → Sources</p>
        {/each}
        {#if available.length}
          <div class="divide-y overflow-hidden rounded-[10px] border bg-card">
            {#each available as { source, item } (`${source.id}/${item.name}`)}
              <button
                type="button"
                class="group flex w-full items-center gap-3 px-3.5 py-3 text-left transition-colors hover:bg-muted/60"
                disabled={busy}
                onclick={() => look(`source:${source.id}/${item.name}`)}
                data-testid="source-addon"
              >
                <span class="min-w-0 flex-1">
                  <span class="block font-medium">{item.name} <span class="fact font-normal">{fromWords(source)}</span></span>
                  {#if item.description}<span class="block text-xs text-muted-foreground">{item.description}</span>{/if}
                </span>
                <ChevronRight class="size-4 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5" />
              </button>
            {/each}
          </div>
        {:else}
          <p class="rounded-[10px] border border-dashed px-4 py-4 text-center text-muted-foreground">Every tool the sources offer is installed.</p>
        {/if}
      </div>
      <form class="space-y-2" onsubmit={(e) => (e.preventDefault(), source.trim() && look(source.trim()))}>
        <label for="addon-source" class="block font-medium">From a folder or an archive</label>
        <div class="flex gap-2">
          <Input id="addon-source" bind:value={source} placeholder="/path/to/addon or https://…/addon.tar.gz" class="font-mono text-xs" data-testid="addon-source" />
          <Button type="submit" size="sm" variant="outline" disabled={busy || !source.trim()} data-testid="addon-source-look">See it</Button>
        </div>
        <p class="text-xs text-muted-foreground">A folder with a <span class="font-mono">tool.toml</span>, or an https:// .tar.gz of one.</p>
      </form>
      {#if error}<p class="text-danger" data-testid="addon-install-error">{error}</p>{/if}
    </div>
  {/if}
</Dialog>
