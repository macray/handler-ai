<script lang="ts">
  // The prompt line of the terminal: grows with its text, Enter sends. Meant for a `.term-surface`.
  // While the agent works, a page that keeps a queue (`onqueue`) lets Enter queue the message: it
  // is shown above the input, sent when the turn ends, or now (interrupting the turn).
  // Images (pasted, dropped or picked) go with the text when the page passes `takesImages`; when
  // the agent does not take them, the attach button says so.
  // `@` names a file of the session's folder, picked from `findFiles` (the latest changed ones
  // first, then those matching what follows the `@`): its path goes in the text, which every agent
  // reads (its folder is its working directory).
  import type { AvailableCommand } from "@agentclientprotocol/sdk";
  import { MAX_IMAGES, isImage, readImage, type Prompt, type PromptImage } from "../lib/images";
  import { imageSrc } from "../lib/render";

  let {
    busy,
    commands,
    autofocus = false,
    onsend,
    oncancel,
    text = $bindable(""),
    images = $bindable([]),
    takesImages,
    turnStartedAt = null,
    interrupting = false,
    waiting = false,
    queued = null,
    onqueue,
    onsendnow,
    ondeletequeued,
    findFiles,
  }: {
    busy: boolean;
    autofocus?: boolean; // take the focus when shown, unless the user is typing elsewhere
    commands: AvailableCommand[];
    onsend: (prompt: Prompt) => void;
    oncancel: () => void;
    text?: string;
    images?: PromptImage[];
    takesImages?: boolean; // the agent takes images; not given: no attaching here
    turnStartedAt?: number | null; // ms: shown as the turn's elapsed time
    interrupting?: boolean;
    waiting?: boolean; // the turn is held by a question to you (a permission request)
    queued?: Prompt | null;
    onqueue?: (prompt: Prompt) => void;
    onsendnow?: () => void;
    ondeletequeued?: () => void;
    findFiles?: (query: string) => Promise<string[]>; // not given: no `@` here
  } = $props();

  let input: HTMLTextAreaElement | undefined = $state();
  let picker: HTMLInputElement | undefined = $state();
  let notice = $state<string | null>(null); // why an image was not attached
  let dragging = $state(false);
  let reading = $state(0); // images being read: sending waits for them
  let frame = $state(0);
  let clock = $state(Date.now());
  const SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";

  // `@…` right before the caret: the files it may name
  let caret = $state(0);
  let files = $state<string[]>([]);
  let active = $state(0); // the file Enter or Tab picks
  let closedAt = $state<number | null>(null); // the `@` whose list Esc closed
  const mention = $derived.by(() => {
    if (!findFiles) return null;
    const found = /(?:^|\s)@([^\s@]*)$/.exec(text.slice(0, caret));
    if (!found) return null;
    const start = caret - found[1]!.length - 1;
    return start === closedAt ? null : { start, query: found[1]! };
  });
  const picking = $derived(Boolean(mention && files.length));

  $effect(() => {
    const query = mention?.query;
    if (query === undefined || !findFiles) {
      files = [];
      return;
    }
    let current = true;
    const timer = setTimeout(() => {
      findFiles(query)
        .then((found) => {
          if (!current) return;
          files = found;
          active = 0;
        })
        .catch(() => current && (files = []));
    }, 120);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  });

  function pick(path: string): void {
    if (!mention) return;
    const before = text.slice(0, mention.start);
    const after = text.slice(caret).replace(/^\S*/, ""); // the rest of a name being edited
    text = `${before}@${path} ${after.replace(/^ /, "")}`;
    caret = before.length + path.length + 2;
    files = [];
    requestAnimationFrame(() => input?.setSelectionRange(caret, caret));
    input?.focus();
  }

  const suggestions = $derived(
    text.startsWith("/") && !text.includes(" ")
      ? commands.filter((c) => `/${c.name}`.startsWith(text)).slice(0, 8)
      : [],
  );

  $effect(() => {
    void text; // fit the text
    if (!input) return;
    // Measuring collapses the textarea for a moment: hold its box so the page does not move
    // (the output above would be scrolled back, and stop following the end).
    const box = input.parentElement as HTMLElement;
    box.style.height = `${box.offsetHeight}px`;
    input.style.height = "auto";
    input.style.height = `${input.scrollHeight}px`;
    box.style.height = "";
  });

  $effect(() => {
    if (!autofocus || !input) return;
    const active = document.activeElement;
    const typing = active instanceof HTMLElement && active !== input && active.matches("input, textarea, select, [contenteditable]");
    if (!typing) input.focus();
  });

  $effect(() => {
    if (!busy || turnStartedAt === null) return;
    clock = Date.now();
    const timer = setInterval(() => (clock = Date.now()), 1000);
    return () => clearInterval(timer);
  });

  const elapsed = $derived(turnStartedAt === null ? "" : duration(clock - turnStartedAt));

  function duration(ms: number): string {
    const s = Math.max(0, Math.floor(ms / 1000));
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m${String(s % 60).padStart(2, "0")}s`;
    return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}m`;
  }

  $effect(() => {
    if (!busy || waiting || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = setInterval(() => (frame = (frame + 1) % SPINNER.length), 80);
    return () => clearInterval(timer);
  });

  const queues = $derived(busy && Boolean(onqueue));

  const sendable = $derived(
    Boolean(text.trim() || images.length) && (!busy || Boolean(onqueue)) && reading === 0,
  );

  function send(): void {
    if (!sendable) return;
    const prompt = { text: text.trim(), images };
    text = "";
    images = [];
    notice = null;
    if (busy) onqueue?.(prompt);
    else onsend(prompt);
  }

  async function attach(files: File[]): Promise<void> {
    const found = files.filter(isImage);
    if (!found.length) return;
    notice = null;
    if (!takesImages) {
      notice = "This agent does not take images.";
      return;
    }
    const room = MAX_IMAGES - images.length;
    if (found.length > room) notice = `At most ${MAX_IMAGES} images in a message.`;
    for (const file of found.slice(0, Math.max(room, 0))) {
      reading++;
      try {
        images = [...images, await readImage(file)];
      } catch {
        notice = `${file.name || "This image"} could not be read.`;
      } finally {
        reading--;
      }
    }
    input?.focus();
  }

  // A screenshot pasted: attached. A paste that also has text (a spreadsheet's cells come with a
  // picture of them) is pasted as text.
  function paste(event: ClipboardEvent): void {
    const data = event.clipboardData;
    if (takesImages === undefined || !data || data.types.includes("text/plain")) return;
    const files = [...data.files];
    if (!files.some(isImage)) return;
    event.preventDefault();
    void attach(files);
  }

  function dragover(event: DragEvent): void {
    if (takesImages === undefined || !event.dataTransfer?.types.includes("Files")) return;
    event.preventDefault();
    dragging = true;
  }

  function drop(event: DragEvent): void {
    dragging = false;
    if (takesImages === undefined || !event.dataTransfer?.files.length) return;
    event.preventDefault();
    void attach([...event.dataTransfer.files]);
  }

  function keydown(event: KeyboardEvent): void {
    if (picking && !event.isComposing) {
      const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
      if (step) {
        event.preventDefault();
        active = (active + step + files.length) % files.length;
        return;
      }
      if ((event.key === "Enter" && !event.shiftKey) || event.key === "Tab") {
        event.preventDefault();
        pick(files[active]!);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closedAt = mention!.start; // only the list: the turn goes on
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send();
    } else if (event.key === "Escape" && busy) {
      oncancel();
    }
  }
</script>

<div
  class="composer"
  class:dragging
  role="group"
  aria-label="new message"
  ondragover={dragover}
  ondragleave={() => (dragging = false)}
  ondrop={drop}
>
  {#if queued}
    <div class="queued" data-testid="queued">
      <div class="queued-head">
        <span class="text-muted-foreground">{interrupting ? "interrupting… then sent" : busy ? "queued: sent when the agent finishes" : "queued"}</span>
        <span class="spacer"></span>
        {#if !interrupting}
          <button type="button" class="key send" onclick={onsendnow} data-testid="queued-send-now">{busy ? "Send now (interrupts)" : "Send"}</button>
        {/if}
        <button type="button" class="key" onclick={ondeletequeued} data-testid="queued-delete">Delete</button>
      </div>
      {#if queued.images.length}<p class="text-muted-foreground">{queued.images.length} image{queued.images.length === 1 ? "" : "s"}</p>{/if}
      {#if queued.text}<p class="queued-text">{queued.text}</p>{/if}
    </div>
  {/if}
  {#if picking}
    <ul class="suggestions" role="listbox" aria-label="files" data-testid="file-suggestions">
      {#each files as path, n (path)}
        {@const slash = path.lastIndexOf("/") + 1}
        <li role="option" aria-selected={n === active}>
          <button type="button" class:active={n === active} onmousedown={(e) => e.preventDefault()} onclick={() => pick(path)}>
            <span class="text-muted-foreground">@{path.slice(0, slash)}</span><span class="cmd">{path.slice(slash)}</span>
          </button>
        </li>
      {/each}
    </ul>
  {:else if suggestions.length}
    <ul class="suggestions">
      {#each suggestions as c (c.name)}
        <li>
          <button type="button" onclick={() => ((text = `/${c.name} `), input?.focus())}>
            <span class="cmd">/{c.name}</span> <span class="text-muted-foreground">{c.description}</span>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
  {#if images.length}
    <ul class="attached" data-testid="attached-images">
      {#each images as image, n (n)}
        <li>
          <img src={imageSrc({ type: "image", ...image })} alt="image {n + 1}" />
          <button type="button" aria-label="remove image {n + 1}" title="Remove" onclick={() => (images = images.filter((_, i) => i !== n))}>×</button>
        </li>
      {/each}
    </ul>
  {/if}
  {#if reading}<p class="text-muted-foreground notice-line" role="status">reading image…</p>{/if}
  {#if notice}<p class="notice notice-line" role="status" data-testid="image-notice">{notice}</p>{/if}
  <div class="input" class:busy={busy && !onqueue}>
    <span class="prompt" aria-hidden="true">❯</span>
    <textarea
      bind:this={input}
      bind:value={text}
      onkeydown={keydown}
      onkeyup={() => (caret = input?.selectionStart ?? 0)}
      oninput={() => {
        caret = input?.selectionStart ?? 0;
        closedAt = null;
      }}
      onclick={() => (caret = input?.selectionStart ?? 0)}
      onpaste={paste}
      rows="1"
      spellcheck="false"
      placeholder={queues ? "Add a detail: sent when the agent finishes…" : busy ? "the agent is working…" : "Ask the agent…"}
      aria-label="prompt"
    ></textarea>
  </div>
  <div class="hints">
    {#if busy && waiting && !interrupting}
      <span class="waiting" data-testid="waiting">
        <span aria-hidden="true">⏸</span> waiting for you{#if elapsed}&nbsp;<span class="tabular-nums">· {elapsed}</span>{/if}
      </span>
      <button type="button" class="key" onclick={oncancel} data-testid="interrupt">Interrupt</button>
    {:else if busy}
      <span class="working" data-testid="working">
        <span class="spinner" aria-hidden="true">{SPINNER[frame]}</span>
        {interrupting ? "interrupting…" : "working"}{#if elapsed}&nbsp;<span class="tabular-nums" data-testid="elapsed">{elapsed}</span>{/if}
        {#if !interrupting}· <kbd>esc</kbd> to interrupt{/if}
      </span>
      {#if !interrupting}<button type="button" class="key" onclick={oncancel} data-testid="interrupt">Interrupt</button>{/if}
    {:else if picking}
      <span class="text-muted-foreground"><kbd>↑↓</kbd> choose · <kbd>enter</kbd> or <kbd>tab</kbd> pick · <kbd>esc</kbd> close</span>
    {:else}
      <span class="text-muted-foreground">
        <kbd>enter</kbd> send · <kbd>shift+enter</kbd> newline · <kbd>/</kbd> commands{#if findFiles}&nbsp;· <kbd>@</kbd> files{/if}
      </span>
    {/if}
    <span class="spacer"></span>
    {#if takesImages !== undefined}
      <input
        bind:this={picker}
        type="file"
        accept="image/*"
        multiple
        hidden
        onchange={() => {
          void attach([...(picker?.files ?? [])]);
          if (picker) picker.value = "";
        }}
        data-testid="image-input"
      />
      <button
        type="button"
        class="key"
        disabled={!takesImages}
        title={takesImages
          ? "Attach images (or paste or drop them). They are sent to the model's provider with your message."
          : "This agent does not take images"}
        onclick={() => picker?.click()}
        data-testid="attach-image"
      >
        + image
      </button>
    {/if}
    <button type="button" class="key send" onclick={send} disabled={!sendable} data-testid="send">
      {queues ? "Queue ↵" : "Send ↵"}
    </button>
  </div>
</div>

<style>
  .composer {
    position: relative;
  }
  .input {
    display: grid;
    grid-template-columns: 2ch minmax(0, 1fr);
    column-gap: 0.5ch;
    align-items: start;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.45rem 0.6rem;
    background: var(--card);
    transition: border-color 0.15s;
  }
  .input:focus-within {
    border-color: var(--prompt);
  }
  .input.busy {
    opacity: 0.7;
  }
  .prompt {
    color: var(--prompt);
    font-weight: 700;
    line-height: 1.55;
  }
  textarea {
    border: none;
    background: transparent;
    padding: 0;
    resize: none;
    outline: none;
    font: inherit;
    line-height: 1.55;
    max-height: 40vh;
    overflow-y: auto;
    caret-color: var(--prompt);
  }
  textarea::placeholder {
    color: var(--muted-foreground);
  }
  .hints {
    display: flex;
    align-items: center;
    gap: 1ch;
    margin-top: 0.35rem;
    font-size: max(0.9em, 12px);
    min-height: 1.8em;
  }
  .spacer {
    flex: 1;
  }
  .working {
    color: var(--ok);
  }
  .waiting {
    color: var(--warn);
    font-weight: 600;
  }
  kbd {
    font: inherit;
    color: var(--foreground);
  }
  .key {
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0.1rem 0.6rem;
    font-size: 1em;
  }
  .send:not(:disabled) {
    color: var(--prompt);
    border-color: var(--prompt);
  }
  .composer.dragging .input {
    border-color: var(--prompt);
    border-style: dashed;
  }
  .attached {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    list-style: none;
    margin: 0 0 0.35rem;
    padding: 0;
  }
  .attached li {
    position: relative;
  }
  .attached img {
    display: block;
    height: 3.5rem;
    max-width: 8rem;
    object-fit: cover;
    border: 1px solid var(--border);
    border-radius: 4px;
  }
  .attached button {
    position: absolute;
    top: -0.4rem;
    right: -0.4rem;
    width: 1.2rem;
    height: 1.2rem;
    line-height: 1;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--card);
    font-size: 0.85em;
  }
  .notice-line {
    margin: 0 0 0.35rem;
    font-size: 0.85em;
  }
  .notice {
    color: var(--warn);
  }
  .queued {
    margin: 0 0 0.35rem;
    padding: 0.35rem 0.6rem;
    border: 1px dashed var(--prompt);
    border-radius: 6px;
    background: var(--card);
  }
  .queued-head {
    display: flex;
    align-items: center;
    gap: 1ch;
    font-size: 0.85em;
  }
  .queued-text {
    margin: 0.25rem 0 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 8lh;
    overflow-y: auto;
  }
  .suggestions {
    list-style: none;
    margin: 0 0 0.3rem;
    padding: 0.25rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--card);
  }
  .suggestions button {
    border: none;
    text-align: left;
    width: 100%;
    font-size: 1em;
    padding: 0.15rem 0.4rem;
  }
  .suggestions button:hover,
  .suggestions button.active {
    background: var(--muted);
  }
  .cmd {
    color: var(--link);
  }
</style>
