<script lang="ts">
  // Mini apps (contract H, docs/dev/design/miniapps.md): register a folder, deploy what it holds,
  // open, roll back. Deploying is only ever done here or with `handler app deploy`: agents write
  // apps, people install them.
  import When from "../components/When.svelte";
  import FolderPicker from "../components/FolderPicker.svelte";
  import { Button } from "$lib/components/ui/button";
  import * as Card from "$lib/components/ui/card";
  import { Input } from "$lib/components/ui/input";
  import PageHeader from "../components/PageHeader.svelte";
  import PageTitle from "../components/PageTitle.svelte";
  import StatusBadge from "../components/StatusBadge.svelte";
  import { api } from "../lib/api";
  import type { App } from "../lib/contracts.gen";
  import { remote } from "../lib/remote.svelte";

  let apps = $state<App[]>([]);
  let error = $state<string | null>(null);
  let sourceDir = $state("");
  let busy = $state<Record<string, string>>({}); // app → what it is doing ("deploying"…)
  let problems = $state<Record<string, string>>({});
  let logs = $state<Record<string, string>>({});
  let secretInputs = $state<Record<string, string>>({}); // "app/SECRET" → value being typed
  let shortcutInputs = $state<Record<string, string>>({});

  // Apps are shared with persons, not devices: you ("owner") and the persons family members'
  // devices were paired for (Settings → Remote).
  const devicesOf = $derived.by(() => {
    const out: Record<string, string[]> = { owner: [] };
    for (const d of remote.status?.devices ?? []) (out[d.person ?? "owner"] ??= []).push(d.name);
    return out;
  });

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

  async function add(): Promise<void> {
    error = null;
    try {
      await api.addApp(sourceDir.trim());
      sourceDir = "";
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function act(app: App, doing: string, action: () => Promise<unknown>): Promise<void> {
    busy[app.name] = doing;
    delete problems[app.name];
    try {
      await action();
    } catch (e) {
      problems[app.name] = (e as Error).message;
    } finally {
      delete busy[app.name];
      await load();
      if (logs[app.name] !== undefined) await showLog(app);
    }
  }

  function deploy(app: App): void {
    const added = app.source.addedNeeds ?? [];
    if (added.length && !confirm(`${app.name} ${app.source.version} may reach more than before:\n\n${added.join("\n")}\n\nDeploy?`)) return;
    void act(app, "deploying (tests, health check)…", () => api.deployApp(app.name));
  }

  function rollback(app: App): void {
    const text =
      `Go back to ${app.name} ${app.previous?.version}?\n\n` +
      `Its data goes back to how it was before ${app.current?.version} was deployed: what changed since is lost.`;
    if (confirm(text)) void act(app, "rolling back…", () => api.rollbackApp(app.name));
  }

  function remove(app: App): void {
    if (confirm(`Remove ${app.name}? Its installed versions are deleted; its data folder is kept.`))
      void act(app, "removing…", () => api.removeApp(app.name));
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
      problems[app.name] = (e as Error).message;
    }
  }

  async function showLog(app: App): Promise<void> {
    try {
      logs[app.name] = (await api.appLog(app.name)).text;
    } catch (e) {
      problems[app.name] = (e as Error).message;
    }
  }

  function saveSecret(app: App, secret: string): void {
    const key = `${app.name}/${secret}`;
    const value = (secretInputs[key] ?? "").trim();
    void act(app, "saving…", async () => {
      await api.setAppSecret(app.name, secret, value);
      delete secretInputs[key];
    });
  }

  function unsetSecret(app: App, secret: string): void {
    if (confirm(`Forget ${secret} for ${app.name}?`)) void act(app, "saving…", () => api.unsetAppSecret(app.name, secret));
  }

  function saveShortcut(app: App, keys: string | null): void {
    void act(app, "saving…", async () => {
      await api.setAppShortcut(app.name, keys);
      delete shortcutInputs[app.name];
    });
  }

  function togglePerson(app: App, person: string, on: boolean): void {
    const persons = new Set(app.persons ?? []);
    if (on) persons.add(person);
    else persons.delete(person);
    void act(app, "saving…", () => api.setAppPersons(app.name, [...persons]));
  }

  function deployable(app: App): boolean {
    return !app.source.error && !!app.source.version && app.source.version !== app.current?.version;
  }
</script>

<PageHeader titled title="Apps" />
<div class="flex-1 overflow-y-auto">
  <div class="mx-auto w-full max-w-4xl space-y-8 px-8 py-10">
    <PageTitle title="Apps" description="Mini apps your agents write: deployed, opened and rolled back here." />
    {#if error}<p class="text-sm text-danger" data-testid="apps-error">{error}</p>{/if}

    <section class="space-y-3">
      {#each apps as app (app.name)}
        <Card.Root data-testid="app-card">
          <Card.Header>
            <Card.Title class="flex items-center gap-3">
              <span>{app.name}</span>
              <span class="text-sm font-normal text-muted-foreground">{app.current ? app.current.version : "not deployed"}</span>
              <StatusBadge status={app.state} />
            </Card.Title>
            <Card.Description>
              {app.description ?? app.source.description ?? ""}
              <span class="block truncate font-mono text-xs" title={app.sourceDir}>{app.sourceDir}</span>
            </Card.Description>
          </Card.Header>
          <Card.Content class="space-y-3 text-sm">
            {#if app.source.error}
              <p class="text-danger">Source folder: {app.source.error}</p>
            {:else if deployable(app)}
              <p>
                Version <strong>{app.source.version}</strong> is ready to deploy.
                {#if app.source.addedNeeds?.length}
                  <span class="text-warn">It may reach more than before: {app.source.addedNeeds.join(", ")}.</span>
                {/if}
              </p>
            {/if}
            {#if app.secrets?.length}
              <div class="space-y-2 rounded-md border p-3" data-testid="app-secrets">
                <p class="text-xs text-muted-foreground">
                  Secrets it asks for: entered here, kept by Handler, never in the app's folder. Changing one restarts it.
                </p>
                {#each app.secrets as s (s.name)}
                  {@const key = `${app.name}/${s.name}`}
                  <form class="flex items-center gap-2" onsubmit={(e) => (e.preventDefault(), saveSecret(app, s.name))}>
                    <code class="w-48 shrink-0 truncate text-xs">{s.name}</code>
                    <span class="w-14 shrink-0 text-xs {s.set ? 'text-ok' : 'text-warn'}">{s.set ? "set" : "not set"}</span>
                    <Input
                      type="password"
                      autocomplete="off"
                      class="h-8"
                      placeholder={s.set ? "replace…" : "value"}
                      aria-label={`value of ${s.name}`}
                      bind:value={secretInputs[key]}
                    />
                    <Button size="sm" type="submit" variant="outline" disabled={!secretInputs[key]?.trim()}>Save</Button>
                    {#if s.set}<Button size="sm" variant="ghost" onclick={() => unsetSecret(app, s.name)}>Unset</Button>{/if}
                  </form>
                {/each}
              </div>
            {/if}
            {#if app.current}
              <form
                class="flex items-center gap-2"
                data-testid="app-shortcut"
                onsubmit={(e) => (e.preventDefault(), saveShortcut(app, (shortcutInputs[app.name] ?? "").trim()))}
              >
                <span class="w-48 shrink-0 text-xs text-muted-foreground">Keyboard shortcut (GNOME)</span>
                <Input
                  class="h-8 w-48"
                  placeholder={app.shortcut ?? "<Super>n"}
                  aria-label="keyboard shortcut"
                  bind:value={shortcutInputs[app.name]}
                />
                <Button size="sm" type="submit" variant="outline" disabled={!shortcutInputs[app.name]?.trim()}>Set</Button>
                {#if app.shortcut}
                  <code class="text-xs">{app.shortcut}</code>
                  <Button size="sm" variant="ghost" onclick={() => saveShortcut(app, null)}>Remove</Button>
                {/if}
              </form>
            {/if}
            {#if app.current}
              <div class="flex flex-wrap items-center gap-x-3 gap-y-1" data-testid="app-persons">
                <span class="w-48 shrink-0 text-xs text-muted-foreground">Remote (devices of)</span>
                {#each [...new Set([...Object.keys(devicesOf), ...(app.persons ?? [])])].sort() as person (person)}
                  {@const names = devicesOf[person] ?? []}
                  <label class="flex items-center gap-1.5 text-xs" title={names.length ? names.join(", ") : "no paired device"}>
                    <input
                      type="checkbox"
                      checked={app.persons?.includes(person) ?? false}
                      disabled={!!busy[app.name]}
                      onchange={(e) => togglePerson(app, person, e.currentTarget.checked)}
                    />
                    {person === "owner" ? "you" : person}
                    <span class="text-muted-foreground">({names.length} device{names.length === 1 ? "" : "s"})</span>
                  </label>
                {/each}
              </div>
            {/if}
            {#if app.error}<p class="text-danger">{app.error}</p>{/if}
            {#if problems[app.name]}<p class="text-danger" data-testid="app-problem">{problems[app.name]}</p>{/if}
            <div class="flex flex-wrap items-center gap-2">
              {#if busy[app.name]}
                <span class="text-muted-foreground">{busy[app.name]}</span>
              {:else}
                <Button size="sm" disabled={!app.current} onclick={() => open(app)}>Open</Button>
                <Button size="sm" variant="outline" disabled={!deployable(app)} onclick={() => deploy(app)}>
                  Deploy{deployable(app) ? ` ${app.source.version}` : ""}
                </Button>
                {#if app.previous}
                  <Button size="sm" variant="outline" onclick={() => rollback(app)}>Roll back to {app.previous.version}</Button>
                {/if}
                {#if app.state === "running"}
                  <Button size="sm" variant="ghost" onclick={() => act(app, "stopping…", () => api.stopApp(app.name))}>Stop</Button>
                {/if}
                <Button size="sm" variant="ghost" onclick={() => (logs[app.name] === undefined ? showLog(app) : delete logs[app.name])}>
                  {logs[app.name] === undefined ? "Log" : "Hide log"}
                </Button>
                <Button size="sm" variant="ghost" class="ml-auto text-destructive hover:text-destructive" onclick={() => remove(app)}>Remove</Button>
              {/if}
            </div>
            {#if logs[app.name] !== undefined}
              <pre class="max-h-80 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap">{logs[app.name] || "(empty)"}</pre>
            {/if}
          </Card.Content>
        </Card.Root>
      {:else}
        <p class="rounded-lg border bg-card px-4 py-6 text-center text-sm text-muted-foreground">
          No apps yet. An agent writes one with the <code>miniapp</code> addon; register its folder below.
        </p>
      {/each}
    </section>

    <Card.Root>
      <Card.Header>
        <Card.Title>Add an app</Card.Title>
        <Card.Description>
          The folder holding its <code>app.toml</code>. Nothing is installed until you deploy it; each deploy installs what
          the folder holds then.
        </Card.Description>
      </Card.Header>
      <Card.Content>
        <div class="space-y-3">
          <FolderPicker id="app-source" bind:value={sourceDir} />
          <Button onclick={add} disabled={!sourceDir.trim().startsWith("/")} data-testid="app-add">Add</Button>
        </div>
      </Card.Content>
    </Card.Root>
  </div>
</div>
