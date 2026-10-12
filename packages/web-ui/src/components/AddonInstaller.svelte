<script lang="ts">
  // Installing an addon (contract G.5): from the catalog handler ships, a folder or an https://
  // .tar.gz archive. Nothing is installed before its preview is shown (the hosts its agents may
  // reach, the secrets it asks for, its commands, MCP server, skills, and that its Containerfile
  // runs code when built); the install takes exactly the previewed content (its digest). The
  // catalog's addons not installed yet are listed as cards; a folder or an archive is the
  // exception, behind a link. Installed, the page goes on to its first configuration
  // (`oninstalled`).
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { api } from "../lib/api";
  import type { AddonCatalogEntry, AddonPreview } from "../lib/contracts.gen";

  let { oninstalled }: { oninstalled: (message: string, addon: string) => void } = $props();

  let catalog = $state<AddonCatalogEntry[]>([]);
  let source = $state(""); // a folder or an archive URL typed by the user
  let elsewhere = $state(false); // its field shown
  let preview = $state<AddonPreview | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);

  const available = $derived(catalog.filter((e) => !e.installed));

  async function loadCatalog(): Promise<void> {
    try {
      catalog = await api.addonCatalog();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void loadCatalog();
  });

  /** Show what installing from `at` brings (also an installed addon's update). */
  export async function look(at: string): Promise<void> {
    busy = true;
    error = null;
    try {
      preview = await api.previewAddon(at);
      requestAnimationFrame(() => document.getElementById("addon-preview")?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
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
      const done = await api.installAddon(preview.source, preview.digest);
      const built = done.build ? " (its image is being built: Settings → Images)" : "";
      preview = null;
      source = "";
      elsewhere = false;
      await loadCatalog();
      oninstalled(`${done.addon.name} installed${built}. Next, configure it:`, done.addon.name);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  const replaced: Record<string, string> = {
    builtin: "the built-in addon of that name (yours wins)",
    installed: "the installed one (an update)",
    own: "your own addon of that name: move its folder away first",
  };
</script>

<div class="space-y-3 text-sm" data-testid="addon-installer">
  <div class="space-y-1">
    <h2 class="text-base font-semibold">Available to install</h2>
    <p class="max-w-2xl text-muted-foreground">From the catalog that comes with Handler. You see what one adds before it is installed.</p>
  </div>
  {#if available.length}
    <div class="grid items-start gap-3 md:grid-cols-2">
      {#each available as e (e.name)}
        <div class="flex items-start justify-between gap-3 rounded-lg border border-dashed p-3.5" data-testid="catalog-entry">
          <div class="min-w-0">
            <div class="font-medium">{e.name}</div>
            {#if e.description}<div class="text-xs text-muted-foreground">{e.description}</div>{/if}
          </div>
          <Button size="sm" variant="outline" disabled={busy} onclick={() => look(`catalog:${e.name}`)}>Install…</Button>
        </div>
      {/each}
    </div>
  {:else}
    <p class="text-muted-foreground">Everything in the catalog is installed.</p>
  {/if}
  {#if elsewhere}
    <form class="flex gap-2" onsubmit={(e) => (e.preventDefault(), source.trim() && look(source.trim()))}>
      <Input bind:value={source} placeholder="/path/to/addon or https://…/addon.tar.gz" class="h-8 font-mono text-xs" data-testid="addon-source" />
      <Button type="submit" size="sm" variant="outline" disabled={busy || !source.trim()}>Install…</Button>
      <Button type="button" size="sm" variant="ghost" onclick={() => (elsewhere = false)}>Cancel</Button>
    </form>
  {:else}
    <Button variant="link" size="sm" class="h-auto px-0" onclick={() => (elsewhere = true)} data-testid="addon-elsewhere">Install from a folder or an archive…</Button>
  {/if}

  {#if preview}
    <div class="scroll-mt-6 space-y-1.5 rounded-lg border bg-card p-3.5" id="addon-preview" data-testid="addon-preview">
      <div>
        <span class="font-medium">Install {preview.name}?</span>
        {#if preview.description}<span class="text-muted-foreground"> — {preview.description}</span>{/if}
      </div>
      <div class="font-mono text-xs text-muted-foreground">{preview.source}</div>
      <dl class="grid grid-cols-[9rem_1fr] gap-x-2 gap-y-0.5 text-xs">
        <dt class="text-muted-foreground">its agents reach</dt><dd>{preview.egress?.join(", ") || "no host"}</dd>
        <dt class="text-muted-foreground">secrets it asks for</dt><dd>{preview.secretSlots?.map((s) => s.name).join(", ") || "none"}</dd>
        <dt class="text-muted-foreground">settings</dt><dd>{preview.settings?.map((s) => s.name).join(", ") || "none"}</dd>
        <dt class="text-muted-foreground">programs</dt><dd>{preview.commands?.join(", ") || "none"}</dd>
        <dt class="text-muted-foreground">MCP server</dt><dd>{preview.mcp?.join(" ") || "none"}</dd>
        <dt class="text-muted-foreground">skills</dt><dd>{preview.skills?.join(", ") || "none"}</dd>
        {#if preview.env?.length}<dt class="text-muted-foreground">env</dt><dd>{preview.env.join(", ")}</dd>{/if}
      </dl>
      {#if preview.image}
        <p class="text-xs text-danger">Its Containerfile runs code on this machine when its image {preview.image} is built.</p>
      {/if}
      {#if preview.replaces}<p class="text-xs">Replaces {replaced[preview.replaces]}.</p>{/if}
      <div class="flex gap-2 pt-1">
        <Button size="sm" disabled={busy || preview.replaces === "own"} onclick={install} data-testid="addon-install">Install</Button>
        <Button size="sm" variant="ghost" onclick={() => (preview = null)}>Cancel</Button>
      </div>
    </div>
  {/if}
  {#if error}<p class="text-xs text-danger" data-testid="addon-install-error">{error}</p>{/if}
</div>
