<script lang="ts">
  // A new session from the phone: a project, one of its agents allowed from devices (their
  // "Can be started from your phone" setting in handler), and the request — typed, or dictated where
  // the browser can listen. The host starts it, shares it, and this screen opens it.
  import { app } from "../lib/app.svelte";

  let projectId = $state(app.agents[0]?.projectId ?? "");
  const project = $derived(app.agents.find((p) => p.projectId === projectId));
  let agentId = $state("");
  let request = $state("");
  let starting = $state(false);
  let listening = $state(false);

  // the project's default agent, when it is one of those allowed
  $effect(() => {
    if (project && !project.agents.some((a) => a.id === agentId)) {
      agentId = (project.agents.find((a) => a.default) ?? project.agents[0])?.id ?? "";
    }
  });

  type Recognition = {
    lang: string;
    interimResults: boolean;
    onresult: (e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void;
    onend: () => void;
    onerror: () => void;
    start: () => void;
  };
  const Speech = (globalThis as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition })
    .SpeechRecognition ?? (globalThis as unknown as { webkitSpeechRecognition?: new () => Recognition }).webkitSpeechRecognition;

  function dictate(): void {
    if (!Speech || listening) return;
    const recognition = new Speech();
    recognition.lang = navigator.language;
    recognition.interimResults = false;
    recognition.onresult = (e) => {
      const said = Array.from(e.results, (r) => r[0]?.transcript ?? "").join(" ");
      request = [request.trim(), said.trim()].filter(Boolean).join(" ");
    };
    recognition.onend = recognition.onerror = () => (listening = false);
    listening = true;
    recognition.start();
  }

  async function start(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!agentId) return;
    starting = true;
    await app.start(agentId, request);
    starting = false;
  }
</script>

<header class="bar">
  <button type="button" class="back" onclick={() => (app.composing = false)} aria-label="back to the list">‹</button>
  <h1>New session</h1>
</header>

<form class="page" onsubmit={start} data-testid="new-session">
  {#if !app.agents.length}
    <p class="hint">
      No agent can be started from a device yet: in Handler, edit an agent of a project and turn on
      <strong>Can be started from your phone</strong>.
    </p>
  {:else}
    <label>
      <span>Project</span>
      <select bind:value={projectId} data-testid="new-session-project">
        {#each app.agents as p (p.projectId)}<option value={p.projectId}>{p.project}</option>{/each}
      </select>
    </label>
    <label>
      <span>Agent</span>
      <select bind:value={agentId} data-testid="new-session-agent">
        {#each project?.agents ?? [] as a (a.id)}<option value={a.id}>{a.name}{a.default ? " (default)" : ""}</option>{/each}
      </select>
      {#if project?.agents.find((a) => a.id === agentId)?.description}
        <span class="hint">{project?.agents.find((a) => a.id === agentId)?.description}</span>
      {/if}
    </label>
    <label>
      <span>What do you want to do?</span>
      <textarea bind:value={request} rows="5" placeholder="Empty: an empty chat" data-testid="new-session-request"></textarea>
    </label>
    <div class="actions">
      {#if Speech}
        <button type="button" class="secondary" onclick={dictate} disabled={listening} data-testid="dictate">
          {listening ? "Listening…" : "🎤 Dictate"}
        </button>
      {/if}
      <button type="submit" class="primary" disabled={starting || !agentId} data-testid="new-session-start">
        {starting ? "Starting…" : "Start"}
      </button>
    </div>
    {#if app.startError}<p class="error">{app.startError}</p>{/if}
    <p class="hint">It opens here once your computer has started it, and shows in Handler too.</p>
  {/if}
</form>

<style>
  .bar {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.6rem 0.75rem;
    padding-top: max(0.6rem, env(safe-area-inset-top));
    border-bottom: 1px solid var(--border);
    background: var(--card);
  }
  .back {
    font-size: 1.6em;
    line-height: 1;
    padding: 0 0.5rem 0.1rem;
  }
  h1 {
    font-size: 1.05em;
    font-weight: 600;
  }
  .page {
    flex: 1;
    overflow-y: auto;
    padding: 0.75rem 0.75rem max(1rem, env(safe-area-inset-bottom));
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  label > span:first-child {
    font-size: 0.8em;
    color: var(--muted-foreground);
  }
  select,
  textarea {
    font: inherit;
    padding: 0.6rem 0.7rem;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--card);
    color: inherit;
  }
  textarea {
    resize: vertical;
  }
  .actions {
    display: flex;
    gap: 0.6rem;
    justify-content: flex-end;
  }
  .actions button {
    padding: 0.6rem 1rem;
    border-radius: 10px;
    font-weight: 500;
  }
  .primary {
    background: var(--primary);
    color: var(--primary-foreground);
  }
  .secondary {
    border: 1px solid var(--border);
    background: var(--card);
  }
  .hint {
    font-size: 0.85em;
    color: var(--muted-foreground);
  }
  .error {
    color: var(--danger);
    font-size: 0.9em;
  }
</style>
