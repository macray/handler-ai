<script lang="ts">
  // Accounts (D.9), "Your subscriptions": a subscription one harness logs in with. Started from
  // Model access (start), made here in one dialog (its name, suggested; its plan; who can use it;
  // its login), logged in in one of two ways:
  // - a token login (Claude Code): the person runs the harness's sign-in themselves
  //   (`claude setup-token`) and gives the token it prints, pasted or where they keep it; handler
  //   never runs that sign-in nor reads its output (Anthropic's terms);
  // - a file login (Codex, Vibe): handlerd opens a terminal window on the desktop running
  //   `handler account login` (the harness's own login, on this computer; handler keeps the file it
  //   leaves), and its dialog closes when it changed; or that file, from a login done elsewhere.
  // Renamed here while no agent uses it; deleted anyway, once confirmed: its agents then cannot
  // start until given another account. Its connectors (claude.ai MCP servers) are an option of
  // its own, in its Edit, with its description. Listed by name, once there is one; a row is its
  // program, plan and description after a dot, its state said only when it needs the person,
  // with the one thing to do (Log in, Log in again, Delete…); how it is logged in and its
  // automations' verdict in its Edit. The lists come from Model access.
  import AreaTag from "./AreaTag.svelte";
  import AreasPicker from "./AreasPicker.svelte";
  import { ago } from "../lib/agents";
  import SecretSource, { given, type Source } from "./SecretSource.svelte";
  import type { Snippet } from "svelte";
  import CommandLine from "./CommandLine.svelte";
  import Dialog from "./Dialog.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Label } from "$lib/components/ui/label";
  import { Input } from "$lib/components/ui/input";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { api } from "../lib/api";
  import type { AccountInfo, AccountLoginRequest, HarnessInfo } from "../lib/contracts.gen";
  import { freeName } from "../lib/text";

  let {
    accounts,
    harnesses,
    listed,
    onchange,
  }: {
    accounts: AccountInfo[];
    listed: boolean; // the section shown, even empty (once there is an account or a provider)
    harnesses: HarnessInfo[]; // their login recipes
    onchange: () => Promise<void>; // reloads `accounts`
  } = $props();

  // the panel open: a new account, an account's login, or its name, description, plan, connectors
  type Panel = { kind: "new" } | { kind: "login"; name: string } | { kind: "edit"; name: string };
  let panel = $state<Panel | null>(null);
  let form = $state({ name: "", harness: "", description: "", plan: "", connectors: false, areas: [] as string[] });
  let token = $state<Source>({ kind: "secret", text: "" });
  let error = $state<string | null>(null);
  // a file login's terminal window, while waiting for it: what runs there, and the login it had before
  let waiting = $state<{ shown: string; before: string | null } | null>(null);
  let elsewhere = $state(false); // a file login: giving the file of a login done elsewhere instead
  const WAIT = 3000; // ms between two looks at the account while its login window is open
  const SOON = 30 * 24 * 3600 * 1000; // a token expiring within this is said

  const withLogin = $derived(harnesses.filter((h) => h.login));
  const recipe = (harness: string | null | undefined) => harnesses.find((h) => h.name === harness)?.login;
  /** Its product name ("Claude Code"), from the harnesses Model access loaded. */
  const productName = (harness: string) => harnesses.find((h) => h.name === harness)?.product ?? harness;
  // whether an automation may run an agent on it unattended (I.7), as handler read the vendor's terms
  const UNATTENDED = {
    allowed: "Automations may run agents on it",
    "check-terms": "Automations may run agents on it, but check your subscription's terms first: an API key (a provider) is recommended",
    refused: "Automations never run agents on it: an API key (a provider) is needed",
  } as const;

  function open(next: Panel, account?: AccountInfo): void {
    error = null;
    panel = next;
    waiting = null;
    elsewhere = false;
    token = { kind: "secret", text: "" };
    form = {
      name: account?.name ?? "",
      harness: account?.harness ?? withLogin[0]?.name ?? "",
      description: account?.description ?? "",
      plan: account?.plan ?? "",
      connectors: account?.connectors ?? false,
      areas: account?.areas ?? [],
    };
  }

  /** A new account of this harness, its name suggested (two of one harness: "pro", "perso"). */
  export function start(harness: string): void {
    open({ kind: "new" });
    form.harness = harness;
    form.name = freeName(harness.split("-")[0] ?? harness, accounts.map((a) => a.name));
  }


  async function run(action: () => Promise<unknown>, then: Panel | null = null): Promise<void> {
    error = null;
    try {
      await action();
      panel = then;
      await onchange();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  // the subscription's plan, for a harness that cannot learn it from its login (Claude Code)
  const plans = $derived(recipe(form.harness)?.plans ?? []);
  // its harness can use the account's own connectors (claude.ai MCP servers)
  const hasConnectors = $derived(harnesses.find((h) => h.name === form.harness)?.accountConnectors ?? false);
  const body = () => ({
    name: form.name.trim(),
    harness: form.harness,
    description: form.description.trim() || null,
    plan: plans.includes(form.plan) ? form.plan : null,
    connectors: hasConnectors && form.connectors,
    areas: form.areas,
  });
  /** Create it, then its login: the token given in the same dialog, or its login's terminal
   * window. A login that fails leaves the dialog on its login step, with the error. */
  async function create(): Promise<void> {
    const name = form.name.trim();
    error = null;
    try {
      await api.createAccount(body());
    } catch (e) {
      error = (e as Error).message;
      return;
    }
    panel = { kind: "login", name };
    await onchange();
    if (recipe(form.harness)?.tokenCommand) await saveToken(name);
    else await openWindow(name);
  }
  const save = (name: string) => run(() => api.updateAccount(name, body()));
  function saveToken(name: string): Promise<void> {
    const it = given(token);
    const request: AccountLoginRequest = "value" in it ? { token: it.value } : { tokenRef: it.ref };
    return run(() => api.setAccountLogin(name, request));
  }
  function remove(a: AccountInfo): void {
    const used = a.agents?.length
      ? `\n\nUsed by ${a.agents.join(", ")}: they will not start until you give them another account.`
      : "";
    if (confirm(`Delete the account ${a.name} and its login?${used}`)) void run(() => api.deleteAccount(a.name));
  }

  // the dialog: the account it is about, its title
  const current = $derived.by(() => {
    const name = panel && "name" in panel ? panel.name : null;
    return accounts.find((a) => a.name === name);
  });
  const title = $derived(
    panel?.kind === "new" ? `Connect ${recipe(form.harness)?.subscription ?? "a subscription"}` : panel?.kind === "login" ? `Log in ${panel.name}` : panel?.kind === "edit" ? `Edit ${panel.name}` : "",
  );
  const subtitle = $derived(
    panel?.kind === "new" ? signIn(form.harness) : panel?.kind === "login" && current ? signIn(current.harness) : panel?.kind === "edit" && current ? use(current) : undefined,
  );
  /** Whose sign-in it is: the vendor's, run by the person, for their own use (vendors' terms). */
  function signIn(harness: string | null | undefined): string {
    const login = recipe(harness);
    if (!harness || !login) return "";
    const product = productName(harness);
    const own = login.tokenCommand ? `${product}'s own sign-in: you run it, Handler keeps the token.` : `${product}'s own sign-in, on this computer.`;
    return `${login.subscription} · via ${product}, for your own use. ${own}`;
  }
  /** What uses it, said in its Edit (and before it is deleted), not on its line. */
  function use(a: AccountInfo): string {
    const sessions = `${a.sessions ?? 0} session${a.sessions === 1 ? "" : "s"}${a.lastUsedAt ? `, last ${ago(a.lastUsedAt)}` : ""}`;
    return `${a.agents?.length ? `Used by ${a.agents.join(", ")}` : "No agent uses it"}${a.connectors ? ", with its connectors" : ""} · ${sessions}.`;
  }
  function close(): void {
    panel = null;
    waiting = null;
    error = null;
  }

  /** A file login: a terminal window on the desktop runs it; the card follows the account until its login changed. */
  async function openWindow(name: string): Promise<void> {
    error = null;
    const before = accounts.find((a) => a.name === name)?.loggedInAt ?? null;
    try {
      const opened = await api.openLoginWindow(name);
      waiting = { shown: `${opened.terminal}: ${opened.command}`, before };
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    if (!waiting || panel?.kind !== "login") return;
    const name = panel.name;
    const before = waiting.before;
    const timer = setInterval(async () => {
      await onchange();
      const now = accounts.find((a) => a.name === name);
      if (now?.status === "ready" && (now.loggedInAt ?? null) !== before) {
        waiting = null;
        panel = null;
      }
    }, WAIT);
    return () => clearInterval(timer);
  });

  async function upload(name: string, input: HTMLInputElement): Promise<void> {
    const file = input.files?.[0];
    if (file) await run(async () => api.setAccountLogin(name, { file: await file.text() }));
  }

  /** Its login, in a few words: how it is logged in and until when (quiet: only on hover and in
   * its Edit, the line keeps its dot), or what is missing. */
  function status(a: AccountInfo): { text: string; tone: string; renew: boolean; quiet: boolean } {
    if (a.status === "invalid") return { text: "Can't be used", tone: "text-danger", renew: false, quiet: false };
    if (a.status === "incomplete") {
      const text = (a.problems ?? []).join("; ") || "not logged in";
      return { text: text.charAt(0).toUpperCase() + text.slice(1), tone: "text-warn", renew: false, quiet: false };
    }
    const where = { secret: "token kept by Handler", env: "token from an environment variable", file: "token from a file", command: "token from a command" };
    const how = a.token ? `Logged in · ${where[a.token]}` : "Logged in";
    if (a.expiresAt) {
      const left = new Date(a.expiresAt).getTime() - Date.now();
      if (left < SOON) return { text: `Login ends in ${Math.max(1, Math.ceil(left / 86_400_000))} days`, tone: "text-warn", renew: true, quiet: false };
      return { text: `${how} · until ${a.expiresAt.slice(0, 10)}`, tone: "text-ok", renew: false, quiet: true };
    }
    return { text: how, tone: "text-ok", renew: false, quiet: true };
  }

  /** Its login again: a token form, or (a file login) its terminal window at once. */
  function logIn(a: AccountInfo): void {
    open({ kind: "login", name: a.name }, a);
    if (!recipe(a.harness)?.tokenCommand) void openWindow(a.name);
  }

  const sorted = $derived([...accounts].sort((a, b) => a.name.localeCompare(b.name)));
</script>

{#snippet field(label: string, id: string, body: Snippet, hint?: string)}
  <div class="space-y-1.5">
    <Label for={id}>{label}</Label>
    {@render body()}
    {#if hint}<p class="text-xs text-muted-foreground">{hint}</p>{/if}
  </div>
{/snippet}

<!-- a numbered step of a login -->
{#snippet step(n: number, body: Snippet)}
  <li class="flex gap-3">
    <span class="flex size-5 shrink-0 items-center justify-center rounded-full bg-muted font-mono text-[11px] text-muted-foreground">{n}</span>
    <div class="min-w-0 flex-1 space-y-2">{@render body()}</div>
  </li>
{/snippet}

<!-- a token login: the command the person runs, what it prints, where Handler takes it from -->
{#snippet tokenSteps(harness: string)}
  {@const login = recipe(harness)}
  {#if login?.tokenCommand}
    <ol class="space-y-4 rounded-[10px] border bg-muted/30 p-4" data-testid="account-token-steps">
      {#snippet run()}
        <p>In a terminal where {productName(harness)} is installed, run</p>
        <CommandLine command={login?.tokenCommand ?? ""} />
      {/snippet}
      {#snippet prints()}
        <p>Sign in on the page it opens. At the end it prints a token{#if login?.tokenPrefix}{" "}that starts with <span class="fact">{login.tokenPrefix}</span>{/if}.</p>
        {#if login?.tokenPrefix}<p class="text-xs text-muted-foreground">A code that page shows goes back into the terminal: it is not the token.</p>{/if}
      {/snippet}
      {#snippet give()}
        <p>Give it here</p>
        <SecretSource bind:source={token} placeholder={login?.tokenPrefix ? `${login.tokenPrefix}…` : "the token it printed"} />
        <p class="text-xs text-muted-foreground">
          {#if login?.tokenLifetimeDays}It lasts {login.tokenLifetimeDays} days, for any number of sessions.{/if}
          Pasted, Handler keeps it sealed: agents get a stand-in.
        </p>
      {/snippet}
      {@render step(1, run)}
      {@render step(2, prints)}
      {@render step(3, give)}
    </ol>
  {/if}
{/snippet}

<!-- the fields of an account's Edit: name, plan, description, areas, connectors -->
{#snippet fields()}
  {#snippet name()}<Input id="account-name" placeholder="e.g. claude-perso" bind:value={form.name} required data-testid="account-name" />{/snippet}
  {#snippet plan()}
    <NativeSelect.Root id="account-plan" class="w-full" bind:value={form.plan} data-testid="account-plan">
      <NativeSelect.Option value="">not set</NativeSelect.Option>
      {#each plans as p (p)}<NativeSelect.Option value={p}>{p}</NativeSelect.Option>{/each}
    </NativeSelect.Root>
  {/snippet}
  {#snippet description()}<Input id="account-description" placeholder="e.g. your email" bind:value={form.description} />{/snippet}
  <div class="grid gap-4 sm:grid-cols-2">
    {@render field("Name", "account-name", name, "Yours to choose: two of one kind, e.g. pro and perso.")}
    {#if plans.length}{@render field("Plan", "account-plan", plan, "Its sign-in does not tell.")}{/if}
  </div>
  {@render field("Description (optional)", "account-description", description)}
  <AreasPicker bind:value={form.areas} />
  {#if hasConnectors}
    <label class="flex items-start gap-2.5">
      <Checkbox class="mt-0.5" bind:checked={form.connectors} data-testid="account-connectors" />
      <span>
        Its connectors <span class="block text-xs text-warn">The MCP servers connected to the account on claude.ai: they reach whatever the account connected.</span>
      </span>
    </label>
  {/if}
{/snippet}

{#if accounts.length || listed}
  <section class="enter space-y-3" id="accounts" data-testid="accounts">
    <h2 class="flex flex-wrap items-baseline gap-x-2 text-base font-semibold">
      Your subscriptions
      {#if accounts.length}<span class="font-mono text-xs font-normal text-muted-foreground">{accounts.length}</span>{/if}
      <span class="text-xs font-normal text-muted-foreground">· for your own use, in sessions you start and follow</span>
    </h2>
    {#if error && !panel}<p class="text-sm text-danger" data-testid="account-error">{error}</p>{/if}
    {#if accounts.length}
      <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
        {#each sorted as a (a.name)}
          {@const login = recipe(a.harness)}
          {@const shown = status(a)}
          <li class="flex items-center gap-x-4 px-4 py-3" data-testid="account-card">
            <span class="hidden size-8 shrink-0 items-center justify-center rounded-lg border bg-muted/50 text-xs font-semibold text-muted-foreground sm:flex" aria-hidden="true"
              >{(login?.subscription ?? a.name).charAt(0).toUpperCase()}</span
            >
            <div class="min-w-0 flex-1 space-y-0.5">
              <p class="flex flex-wrap items-center gap-2">
                <span class="truncate font-medium">{a.name}</span>
                {#each a.areas ?? [] as c (c)}<AreaTag name={c} />{/each}
              </p>
              <p class="truncate text-xs text-muted-foreground">
                <!-- logged in: the dot alone, its detail on hover and in Edit; else what needs you -->
                <span class={shown.tone} title={shown.text} data-testid="account-status"
                  >●{#if shown.quiet}<span class="sr-only">{" "}{shown.text}</span>{:else}{" "}{shown.text}{/if}</span
                >
                {#if a.status === "invalid" && a.error}<span class="whitespace-normal">{" "}· {a.error}</span>
                {:else}<span>{shown.quiet ? " " : " · "}{[a.harness ? productName(a.harness) : null, a.plan, a.description].filter(Boolean).join(" · ")}</span>{/if}
              </p>
              {#if a.error && a.status !== "invalid"}<p class="text-xs whitespace-normal text-danger">{a.error}</p>{/if}
            </div>
            <div class="flex shrink-0 items-center gap-1.5">
              {#if a.status === "invalid"}
                <Button variant="outline" size="sm" onclick={() => remove(a)} data-testid="account-delete-row">Delete…</Button>
              {:else if login && (a.status !== "ready" || shown.renew)}
                <Button variant="outline" size="sm" onclick={() => logIn(a)} data-testid="account-log-in">{a.status === "ready" ? "Log in again" : "Log in"}</Button>
              {/if}
              {#if a.harness}
                <Button variant="ghost" size="sm" onclick={() => open({ kind: "edit", name: a.name }, a)} data-testid="account-edit">Edit</Button>
              {/if}
            </div>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="rounded-[10px] border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">No subscription yet. A Claude, ChatGPT or Mistral plan you pay for, for your own use.</p>
    {/if}
  </section>
{/if}

<Dialog bind:open={() => panel !== null, (v) => (v ? null : close())} title={title} description={subtitle} testid="account-dialog">
  {#if panel?.kind === "new"}
    {@const login = recipe(form.harness)}
    <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void create())} data-testid="account-form">
      {#snippet name()}<Input id="account-name" bind:value={form.name} required class="font-mono" data-testid="account-name" />{/snippet}
      {#snippet plan()}
        <NativeSelect.Root id="account-plan" class="w-full" bind:value={form.plan} data-testid="account-plan">
          <NativeSelect.Option value="">not set</NativeSelect.Option>
          {#each plans as p (p)}<NativeSelect.Option value={p}>{p}</NativeSelect.Option>{/each}
        </NativeSelect.Root>
      {/snippet}
      <div class="grid gap-4 sm:grid-cols-2">
        {@render field("Name", "account-name", name, "Change it if you like: two of one kind, e.g. pro and perso.")}
        {#if plans.length}{@render field("Plan", "account-plan", plan, "Its sign-in does not tell.")}{/if}
      </div>
      <AreasPicker bind:value={form.areas} />
      {#if login?.tokenCommand}
        {@render tokenSteps(form.harness)}
      {:else if login}
        <div class="space-y-2 rounded-[10px] border bg-muted/30 p-4">
          <p>Connect opens a terminal window on this computer, running its sign-in:</p>
          {#if login.command}<CommandLine command={login.command.join(" ")} />{/if}
          {#if login.help}<p class="text-muted-foreground">{login.help}</p>{/if}
        </div>
      {/if}
      <p class="text-xs text-muted-foreground">A description{#if hasConnectors}{" "}and its connectors{/if} can be set in its Edit afterwards.</p>
      {#if error}<p class="text-danger" data-testid="account-error">{error}</p>{/if}
      <div class="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onclick={close}>Cancel</Button>
        <Button type="submit" size="sm" disabled={!form.name.trim() || (!!login?.tokenCommand && !token.text.trim())} data-testid="account-create">Connect</Button>
      </div>
    </form>
  {:else if panel?.kind === "login" && current}
    {@const login = recipe(current.harness)}
    {#if login?.tokenCommand && current.harness}
      <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void saveToken(current.name))} data-testid="account-token-form">
        {@render tokenSteps(current.harness)}
        {#if error}<p class="text-danger" data-testid="account-error">{error}</p>{/if}
        <div class="flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onclick={close}>Cancel</Button>
          <Button type="submit" size="sm" disabled={!token.text.trim()} data-testid="account-token-save">Log in</Button>
        </div>
      </form>
    {:else if login}
      <div class="space-y-5" data-testid="account-login">
        <div class="space-y-2">
          <p>{login.help ?? ""}</p>
          {#if login.command}<CommandLine command={login.command.join(" ")} />{/if}
          <p class="text-xs text-muted-foreground">It runs on this computer.</p>
        </div>
        {#if waiting}
          <p class="flex items-start gap-2.5 rounded-[10px] border bg-muted/40 p-3" data-testid="account-login-window">
            <span class="mt-1.5 size-2 shrink-0 animate-pulse rounded-full bg-warn" aria-hidden="true"></span>
            <span>Follow the login in the terminal window that opened <span class="fact">({waiting.shown})</span>. This closes when it is done.</span>
          </p>
        {/if}
        {#if elsewhere}
          <label class="block space-y-1.5">
            <span class="font-medium">The file its login left</span>
            <input type="file" class="block text-xs" onchange={(e) => upload(current.name, e.currentTarget)} data-testid="account-file" />
          </label>
        {/if}
        {#if error}<p class="text-danger" data-testid="account-error">{error}</p>{/if}
        <div class="flex flex-wrap items-center justify-end gap-2">
          {#if !elsewhere}<Button variant="link" size="sm" class="mr-auto px-0" onclick={() => (elsewhere = true)}>Logged in elsewhere?</Button>{/if}
          <Button variant="ghost" size="sm" onclick={close}>Close</Button>
          <Button variant="outline" size="sm" onclick={() => openWindow(current.name)} data-testid="account-open-terminal">
            {waiting ? "Open another window" : "Open a terminal"}
          </Button>
        </div>
      </div>
    {/if}
  {:else if panel?.kind === "edit" && current}
    {@const login = recipe(current.harness)}
    <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void save(current.name))} data-testid="account-edit-form">
      {@render fields()}
      <p class="text-xs text-muted-foreground" data-testid="account-login-detail">Its login: {status(current).text}.</p>
      {#if login}
        <p class="text-xs {login.unattended === 'allowed' ? 'text-muted-foreground' : 'text-warn'}" data-testid="account-unattended">
          {UNATTENDED[login.unattended]} (<a class="text-link hover:underline" href={login.terms} target="_blank" rel="noreferrer">its terms</a>{#if login.checked}, read on {login.checked}{:else}, not read yet{/if}).
        </p>
      {/if}
      {#if error}<p class="text-danger" data-testid="account-error">{error}</p>{/if}
      <div class="flex flex-wrap items-center justify-end gap-2 border-t pt-4">
        <Button type="button" variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={() => remove(current)} data-testid="account-delete">Delete</Button>
        {#if current.token || current.loggedInAt}
          <Button type="button" variant="ghost" size="sm" onclick={() => run(() => api.forgetAccountLogin(current.name))} data-testid="account-forget">Forget login</Button>
        {/if}
        {#if login && current.status === "ready"}
          <Button type="button" variant="ghost" size="sm" onclick={() => logIn(current)} data-testid="account-log-in-again">Log in again</Button>
        {/if}
        <span class="flex-1"></span>
        <Button type="button" variant="ghost" size="sm" onclick={close}>Cancel</Button>
        <Button type="submit" size="sm" disabled={!form.name.trim()}>Save</Button>
      </div>
    </form>
  {/if}
</Dialog>
