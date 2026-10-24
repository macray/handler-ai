<script lang="ts">
  // Accounts (D.9): a subscription one harness logs in with. Started from Model access (start),
  // made here (a name the person chooses, a harness), then logged in, in one of two ways:
  // - a token login (Claude Code): the person runs the harness's sign-in themselves
  //   (`claude setup-token`) and gives the token it prints, pasted or where they keep it; handler
  //   never runs that sign-in nor reads its output (Anthropic's terms);
  // - a file login (Codex, Vibe): handlerd opens a terminal window on the desktop running
  //   `handler account login` (the harness's own login, on this computer; handler keeps the file it
  //   leaves), and its dialog closes when it changed; or that file, from a login done elsewhere.
  // Renamed here while no agent uses it; deleted anyway, once confirmed: its agents then cannot
  // start until given another account. Its connectors (claude.ai MCP servers) are an option of
  // its own. Listed once there is one; made, logged in and changed in a dialog. The lists come
  // from Model access.
  import { productName } from "../lib/harnesses.svelte";
  import AreaTag from "./AreaTag.svelte";
  import AreasPicker from "./AreasPicker.svelte";
  import { ago } from "../lib/agents";
  import SecretSource, { given, type Source } from "./SecretSource.svelte";
  import type { Snippet } from "svelte";
  import CreditCard from "@lucide/svelte/icons/credit-card";
  import Plus from "@lucide/svelte/icons/plus";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import * as Tooltip from "$lib/components/ui/tooltip";
  import Dialog from "./Dialog.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Label } from "$lib/components/ui/label";
  import { Input } from "$lib/components/ui/input";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { api } from "../lib/api";
  import type { AccountInfo, AccountLoginRequest, HarnessInfo } from "../lib/contracts.gen";

  let {
    accounts,
    harnesses,
    listed,
    onadd,
    onchange,
  }: {
    accounts: AccountInfo[];
    listed: boolean; // the section shown, even empty (once there is an account or a provider)
    onadd: () => void; // its Add: Model access's picker of subscriptions
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
  // whether an automation may run an agent on it unattended (I.7), as handler read the vendor's terms
  const UNATTENDED = {
    allowed: "Automations may run agents on it",
    "check-terms": "Automations may run agents on it, but check your plan's terms first: an API key (a provider) is recommended",
    refused: "Automations never run agents on it: an API key (a provider) is needed",
  } as const;
  // its badge when it is not simply allowed: the sentence above in its tooltip, its terms a click away
  const BADGE = { allowed: "", "check-terms": "automations: check terms", refused: "not for automations" } as const;

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

  /** A new account of this harness; the person names it (two of one harness: "pro", "perso"). */
  export function start(harness: string): void {
    open({ kind: "new" });
    form.harness = harness;
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
  /** Create it, then go on to its login: a token form, or its login's terminal window. */
  async function create(): Promise<void> {
    const name = form.name.trim();
    const byFile = recipe(form.harness)?.file;
    await run(() => api.createAccount(body()), { kind: "login", name }); // the same dialog, its next step
    if (!error && byFile) await openWindow(name);
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
    panel?.kind === "new" ? "New account" : panel?.kind === "login" ? `Log in: ${panel.name}` : panel?.kind === "edit" ? `Edit ${panel.name}` : "",
  );
  const subtitle = $derived(
    panel?.kind === "new" ? "A subscription you pay for, signed in with its own sign-in, for your own use." : panel?.kind === "edit" && current ? use(current) : undefined,
  );
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

  /** Its login, in a few words: how it is logged in and until when, or what is missing. */
  function status(a: AccountInfo): { text: string; tone: string } {
    if (a.status === "invalid") return { text: "● invalid", tone: "text-danger" };
    if (a.status === "incomplete") return { text: `● ${(a.problems ?? []).join("; ") || "not logged in"}`, tone: "text-warn" };
    const where = { secret: "token in Handler", env: "token from an environment variable", file: "token from a file", command: "token from a command" };
    const how = a.token ? where[a.token] : "logged in";
    if (a.expiresAt) {
      const left = new Date(a.expiresAt).getTime() - Date.now();
      if (left < SOON) return { text: `● ${how}, expires in ${Math.max(1, Math.ceil(left / 86_400_000))} days: make a new one`, tone: "text-warn" };
      return { text: `● ${how}, until ${a.expiresAt.slice(0, 10)}`, tone: "text-ok" };
    }
    return { text: `● ${how}`, tone: "text-ok" };
  }
</script>

{#snippet field(label: string, id: string, body: Snippet, hint?: string)}
  <div class="space-y-1.5">
    <Label for={id}>{label}</Label>
    {@render body()}
    {#if hint}<p class="text-xs text-muted-foreground">{hint}</p>{/if}
  </div>
{/snippet}

{#snippet command(text: string)}
  <code class="block w-fit max-w-full overflow-x-auto rounded-md bg-muted px-2.5 py-1.5 font-mono text-xs">{text}</code>
{/snippet}

<!-- the fields of a new account and of its Edit: name, plan, description, areas, connectors -->
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
  <section class="enter space-y-4" id="accounts" data-testid="accounts">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div class="space-y-1">
        <h2 class="flex items-center gap-2 text-base font-semibold">
          Accounts <span class="rounded-md bg-muted px-1.5 py-0.5 text-xs font-normal text-muted-foreground">subscription</span>
        </h2>
        <p class="max-w-2xl text-sm text-muted-foreground">
          Plans you pay for, each signed in with its agent program's own sign-in (Claude Code: your own <code>claude setup-token</code>), for your own use.
        </p>
      </div>
      <Button variant="outline" size="sm" onclick={onadd} data-testid="add-account"><Plus />Add an account</Button>
    </div>
    {#if error && !panel}<p class="text-sm text-danger" data-testid="account-error">{error}</p>{/if}
    {#if accounts.length}
      <Tooltip.Provider delayDuration={150}>
        <ul class="divide-y overflow-hidden rounded-[10px] border bg-card text-sm shadow-panel">
          {#each accounts as a (a.name)}
            {@const login = recipe(a.harness)}
            {@const shown = status(a)}
            <li class="flex flex-wrap items-start gap-x-4 gap-y-3 px-4 py-4" data-testid="account-card">
              <span class="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:flex"><CreditCard class="size-4" /></span>
              <div class="min-w-0 flex-1 basis-60 space-y-1">
                <p class="flex flex-wrap items-center gap-2">
                  <span class="truncate font-medium">{a.name}</span>
                  {#if a.harness}<span class="rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{productName(a.harness)}{#if a.plan} · {a.plan}{/if}</span>{/if}
                  {#each a.areas ?? [] as c (c)}<AreaTag name={c} />{/each}
                  {#if login && login.unattended !== "allowed"}
                    <Tooltip.Root>
                      <Tooltip.Trigger>
                        {#snippet child({ props })}
                          <a
                            {...props}
                            href={login.terms}
                            target="_blank"
                            rel="noreferrer"
                            class="inline-flex items-center gap-1 rounded-md bg-warn/10 px-1.5 py-0.5 text-xs text-warn hover:bg-warn/15"
                            data-testid="account-unattended"
                          >
                            <TriangleAlert class="size-3" />{BADGE[login.unattended]}
                          </a>
                        {/snippet}
                      </Tooltip.Trigger>
                      <Tooltip.Content class="max-w-xs">
                        {UNATTENDED[login.unattended]}. Its terms{#if login.checked}, read on {login.checked}{:else}, not read yet{/if}: click to open them.
                      </Tooltip.Content>
                    </Tooltip.Root>
                  {/if}
                </p>
                {#if a.description}<p class="truncate text-xs text-muted-foreground">{a.description}</p>{/if}
                <p class="text-xs {shown.tone}" data-testid="account-status">{shown.text}</p>
                {#if a.error}<p class="text-xs whitespace-normal text-danger">{a.error}</p>{/if}
              </div>
              {#if a.harness}
                <div class="ml-auto flex shrink-0 gap-1.5">
                  {#if login?.tokenCommand}
                    <Button variant="outline" size="sm" onclick={() => open({ kind: "login", name: a.name }, a)} data-testid="account-log-in">{a.token ? "New token" : "Give its token"}</Button>
                  {:else}
                    <Button variant="outline" size="sm" onclick={() => (open({ kind: "login", name: a.name }, a), void openWindow(a.name))} data-testid="account-log-in">{a.status === "ready" ? "Log in again" : "Log in"}</Button>
                  {/if}
                  <Button variant="ghost" size="sm" onclick={() => open({ kind: "edit", name: a.name }, a)} data-testid="account-edit">Edit</Button>
                </div>
              {/if}
            </li>
          {/each}
        </ul>
      </Tooltip.Provider>
    {:else}
      <p class="rounded-[10px] border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">No account yet. A Claude, ChatGPT or Mistral plan you pay for, for your own use.</p>
    {/if}
  </section>
{/if}

<Dialog bind:open={() => panel !== null, (v) => (v ? null : close())} title={title} description={subtitle} testid="account-dialog">
  {#if panel?.kind === "new"}
    <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void create())} data-testid="account-form">
      {#snippet harness()}
        <NativeSelect.Root id="account-harness" class="w-full" bind:value={form.harness} data-testid="account-harness">
          {#each withLogin as h (h.name)}<NativeSelect.Option value={h.name}>{h.login?.subscription} · {h.product}</NativeSelect.Option>{/each}
        </NativeSelect.Root>
      {/snippet}
      {@render field("Subscription", "account-harness", harness)}
      {@render fields()}
      {#if error}<p class="text-danger" data-testid="account-error">{error}</p>{/if}
      <div class="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onclick={close}>Cancel</Button>
        <Button type="submit" size="sm" disabled={!form.name.trim()}>Create</Button>
      </div>
    </form>
  {:else if panel?.kind === "login" && current}
    {@const login = recipe(current.harness)}
    {#if login?.tokenCommand}
      <form class="space-y-5" onsubmit={(e) => (e.preventDefault(), void saveToken(current.name))} data-testid="account-token-form">
        <div class="space-y-2">
          <p>Run this yourself, then give the token it prints:</p>
          {@render command(login.tokenCommand)}
          <p class="text-muted-foreground">
            {login.help ?? ""}
            {#if login.tokenLifetimeDays}It lasts {login.tokenLifetimeDays} days, for any number of sessions.{/if}
          </p>
        </div>
        <div class="space-y-1.5">
          <span class="text-sm font-medium">The token</span>
          <SecretSource bind:source={token} placeholder="the token it printed" />
        </div>
        {#if error}<p class="text-danger" data-testid="account-error">{error}</p>{/if}
        <div class="flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onclick={close}>Cancel</Button>
          <Button type="submit" size="sm" disabled={!token.text.trim()} data-testid="account-token-save">Save</Button>
        </div>
      </form>
    {:else if login}
      <div class="space-y-5" data-testid="account-login">
        <div class="space-y-2">
          <p>{login.help ?? ""}</p>
          {#if login.command}{@render command(login.command.join(" "))}{/if}
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
      {#if login}
        <p class="text-xs {login.unattended === 'allowed' ? 'text-muted-foreground' : 'text-warn'}">
          {UNATTENDED[login.unattended]} (<a class="text-link hover:underline" href={login.terms} target="_blank" rel="noreferrer">its terms</a>{#if login.checked}, read on {login.checked}{:else}, not read yet{/if}).
        </p>
      {/if}
      {#if error}<p class="text-danger" data-testid="account-error">{error}</p>{/if}
      <div class="flex flex-wrap items-center justify-end gap-2 border-t pt-4">
        <Button type="button" variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={() => remove(current)} data-testid="account-delete">Delete</Button>
        {#if current.token || current.loggedInAt}
          <Button type="button" variant="ghost" size="sm" onclick={() => run(() => api.forgetAccountLogin(current.name))} data-testid="account-forget">Forget login</Button>
        {/if}
        <span class="flex-1"></span>
        <Button type="button" variant="ghost" size="sm" onclick={close}>Cancel</Button>
        <Button type="submit" size="sm" disabled={!form.name.trim()}>Save</Button>
      </div>
    </form>
  {/if}
</Dialog>
