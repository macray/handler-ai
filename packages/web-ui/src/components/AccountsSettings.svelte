<script lang="ts">
  // Accounts (D.9): a subscription one harness logs in with. Started from Model access (start),
  // made here (a name the person chooses, a harness), then logged in, in one of two ways:
  // - a token login (Claude Code): the person runs the harness's sign-in themselves
  //   (`claude setup-token`) and gives the token it prints, pasted or where they keep it; handler
  //   never runs that sign-in nor reads its output (Anthropic's terms);
  // - a file login (Codex, Vibe): handlerd opens a terminal window on the desktop running
  //   `handler account login` (the harness's own login, on this computer; handler keeps the file it
  //   leaves), and the card updates when it changed; or that file, from a login done elsewhere.
  // Renamed here while no agent uses it; deleted anyway, once confirmed: its agents then cannot
  // start until given another account. Its connectors (claude.ai MCP servers) are an option of
  // its own. Shown once there is one, or one being made. The lists come from Model access.
  import { productName } from "../lib/harnesses.svelte";
  import ContextTag from "./ContextTag.svelte";
  import ContextsPicker from "./ContextsPicker.svelte";
  import When from "./When.svelte";
  import SecretSource, { given, type Source } from "./SecretSource.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import * as NativeSelect from "$lib/components/ui/native-select";
  import { api } from "../lib/api";
  import type { AccountInfo, AccountLoginRequest, HarnessInfo } from "../lib/contracts.gen";

  let {
    accounts,
    harnesses,
    onchange,
  }: {
    accounts: AccountInfo[];
    harnesses: HarnessInfo[]; // their login recipes
    onchange: () => Promise<void>; // reloads `accounts`
  } = $props();

  // the panel open: a new account, an account's login, or its name, description, plan, connectors
  type Panel = { kind: "new" } | { kind: "login"; name: string } | { kind: "edit"; name: string };
  let panel = $state<Panel | null>(null);
  let form = $state({ name: "", harness: "", description: "", plan: "", connectors: false, contexts: [] as string[] });
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
      contexts: account?.contexts ?? [],
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
    contexts: form.contexts,
  });
  /** Create it, then go on to its login: a token form, or its login's terminal window. */
  async function create(): Promise<void> {
    const name = form.name.trim();
    const byFile = recipe(form.harness)?.file;
    await run(() => api.createAccount(body()));
    if (error) return;
    open({ kind: "login", name });
    if (byFile) await openWindow(name);
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

{#snippet planSelect()}
  {#if plans.length}
    <NativeSelect.Root class="w-40" bind:value={form.plan} title="its subscription's plan: its sign-in does not tell" data-testid="account-plan">
      <NativeSelect.Option value="">plan not set</NativeSelect.Option>
      {#each plans as p (p)}<NativeSelect.Option value={p}>{p}</NativeSelect.Option>{/each}
    </NativeSelect.Root>
  {/if}
  {#if hasConnectors}
    <label class="flex items-center gap-1.5 text-xs" title="the MCP servers connected to the account on claude.ai: they reach whatever the account connected">
      <input type="checkbox" bind:checked={form.connectors} data-testid="account-connectors" />
      Its connectors <span class="text-warn">(they reach what the account connected)</span>
    </label>
  {/if}
{/snippet}

{#if accounts.length || panel?.kind === "new"}
  <section class="scroll-mt-6 space-y-4" id="accounts" data-testid="accounts">
    <div class="space-y-1">
      <h2 class="flex items-center gap-2 text-base font-semibold">
        Accounts <span class="rounded-md bg-muted px-1.5 py-0.5 text-xs font-normal text-muted-foreground">subscription</span>
      </h2>
      <p class="max-w-2xl text-sm text-muted-foreground">
        Plans you pay for, each signed in with its agent program's own sign-in (Claude Code: your own <code>claude setup-token</code>), for your own use.
      </p>
    </div>
    {#if error}<p class="text-sm text-danger" data-testid="account-error">{error}</p>{/if}
    {#if panel?.kind === "new"}
      <form class="flex flex-wrap items-end gap-2 rounded-lg border bg-card p-3" onsubmit={(e) => (e.preventDefault(), void create())} data-testid="account-form">
        <Input class="w-40" placeholder="name, e.g. claude-perso" bind:value={form.name} required data-testid="account-name" />
        <NativeSelect.Root class="w-72" bind:value={form.harness} data-testid="account-harness">
          {#each withLogin as h (h.name)}<NativeSelect.Option value={h.name}>{h.login?.subscription} · {h.product}</NativeSelect.Option>{/each}
        </NativeSelect.Root>
        {@render planSelect()}
        <Input class="min-w-48 flex-1" placeholder="description (optional), e.g. your email" bind:value={form.description} />
        <div class="basis-full"><ContextsPicker bind:value={form.contexts} /></div>
        <Button type="submit" size="sm" disabled={!form.name.trim()}>Create</Button>
        <Button type="button" variant="ghost" size="sm" onclick={() => (panel = null)}>Cancel</Button>
      </form>
    {/if}
    <div class="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-3">
      {#each accounts as a (a.name)}
        {@const login = recipe(a.harness)}
        {@const shown = status(a)}
        <div class="flex flex-col gap-2 rounded-lg border bg-card p-3.5 text-sm" data-testid="account-card">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <div class="truncate font-medium">{a.name}</div>
              {#if a.description}<div class="truncate text-xs text-muted-foreground">{a.description}</div>{/if}
            </div>
            {#if a.harness}<span class="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{productName(a.harness)}{#if a.plan} · {a.plan}{/if}</span>{/if}
          </div>
          {#if a.contexts?.length}<div class="flex flex-wrap gap-1">{#each a.contexts as c (c)}<ContextTag name={c} />{/each}</div>{/if}
          <p class="text-xs {shown.tone}" data-testid="account-status">{shown.text}</p>
          {#if a.error}<p class="text-xs whitespace-normal text-danger">{a.error}</p>{/if}
          {#if login}
            <p class="text-xs {login.unattended === 'allowed' ? 'text-muted-foreground' : 'text-warn'}" data-testid="account-unattended">
              {UNATTENDED[login.unattended]}
              (<a class="text-link hover:underline" href={login.terms} target="_blank" rel="noreferrer">its terms</a>{#if login.checked}, read on {login.checked}{:else}, not read yet{/if}).
            </p>
          {/if}
          <p class="text-xs text-muted-foreground" data-testid="account-use">
            {a.agents?.length ? a.agents.join(", ") : "no agent"}{#if a.connectors} · connectors{/if} · {a.sessions ?? 0} session{a.sessions === 1 ? "" : "s"}{#if a.lastUsedAt}, last <When at={a.lastUsedAt} />{/if}
          </p>
          {#if panel?.kind === "login" && panel.name === a.name && login?.tokenCommand}
            <form class="space-y-2 text-xs" onsubmit={(e) => (e.preventDefault(), void saveToken(a.name))} data-testid="account-token-form">
              <p>
                Run <code class="rounded bg-muted px-1">{login.tokenCommand}</code> yourself. {login.help ?? ""}
                {#if login.tokenLifetimeDays}<span class="text-muted-foreground">It lasts {login.tokenLifetimeDays} days, for any number of sessions.</span>{/if}
              </p>
              <SecretSource bind:source={token} placeholder="the token it printed" />
              <div class="flex gap-2">
                <Button type="submit" size="sm" disabled={!token.text.trim()} data-testid="account-token-save">Save</Button>
                <Button type="button" variant="ghost" size="sm" onclick={() => (panel = null)}>Cancel</Button>
              </div>
            </form>
          {:else if panel?.kind === "login" && panel.name === a.name && login}
            <div class="space-y-2 text-xs" data-testid="account-login">
              <p>{login.help ?? ""} <span class="text-muted-foreground">(<code>{login.command?.join(" ")}</code>, on this computer)</span></p>
              {#if waiting}
                <p class="text-muted-foreground" data-testid="account-login-window">
                  Follow the login in the terminal window that opened ({waiting.shown}); this card updates when it is done.
                </p>
              {/if}
              <div class="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onclick={() => openWindow(a.name)} data-testid="account-open-terminal">
                  {waiting ? "Open another window" : "Open a terminal"}
                </Button>
                <Button variant="ghost" size="sm" onclick={() => (panel = null)}>Close</Button>
                {#if !elsewhere}<Button variant="link" size="sm" onclick={() => (elsewhere = true)}>Logged in elsewhere?</Button>{/if}
              </div>
              {#if elsewhere}
                <label class="block">The file its login left: <input type="file" class="text-xs" onchange={(e) => upload(a.name, e.currentTarget)} data-testid="account-file" /></label>
              {/if}
            </div>
          {:else if panel?.kind === "edit" && panel.name === a.name}
            <form class="space-y-2" onsubmit={(e) => (e.preventDefault(), void save(a.name))}>
              <Input bind:value={form.name} required />
              <Input placeholder="description" bind:value={form.description} />
              {@render planSelect()}
              <ContextsPicker bind:value={form.contexts} />
              <div class="flex gap-2"><Button type="submit" size="sm">Save</Button><Button type="button" variant="ghost" size="sm" onclick={() => (panel = null)}>Cancel</Button></div>
            </form>
          {/if}
          {#if a.harness && !(panel && "name" in panel && panel.name === a.name)}
            <div class="flex flex-wrap gap-1">
              {#if login?.tokenCommand}
                <Button variant="outline" size="sm" onclick={() => open({ kind: "login", name: a.name }, a)} data-testid="account-log-in">{a.token ? "New token" : "Give its token"}</Button>
              {:else}
                <Button variant="outline" size="sm" onclick={() => (open({ kind: "login", name: a.name }, a), void openWindow(a.name))} data-testid="account-log-in">{a.status === "ready" ? "Log in again" : "Log in"}</Button>
              {/if}
              <Button variant="ghost" size="sm" onclick={() => open({ kind: "edit", name: a.name }, a)}>Edit</Button>
              {#if a.token || a.loggedInAt}<Button variant="ghost" size="sm" onclick={() => run(() => api.forgetAccountLogin(a.name))} data-testid="account-forget">Forget login</Button>{/if}
              <Button variant="ghost" size="sm" class="text-destructive hover:text-destructive" onclick={() => remove(a)} data-testid="account-delete">Delete</Button>
            </div>
          {/if}
        </div>
      {/each}
    </div>
  </section>
{/if}
