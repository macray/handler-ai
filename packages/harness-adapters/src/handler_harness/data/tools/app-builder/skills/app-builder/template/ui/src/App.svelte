<script lang="ts">
  import { api } from "./api";

  type Note = { id: number; text: string; createdAt: string };

  let notes = $state<Note[]>([]);
  let text = $state("");
  let error = $state<string | null>(null);

  async function run(action: () => Promise<Note[]>): Promise<void> {
    error = null;
    try {
      notes = await action();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function add(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    await run(() => api<Note[]>("notes", { method: "POST", body: { text } }));
    if (!error) text = "";
  }

  // dates in words people say: "today 09:12", "yesterday 18:40", "14 Nov"
  function when(iso: string): string {
    const d = new Date(iso);
    const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    const days = Math.round((new Date().setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 864e5);
    if (days === 0) return `today ${time}`;
    if (days === 1) return `yesterday ${time}`;
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }

  $effect(() => {
    void run(() => api<Note[]>("notes"));
  });
</script>

<main>
  <header><h1>Notes</h1>{#if notes.length}<small>{notes.length} {notes.length === 1 ? "note" : "notes"}</small>{/if}</header>
  <form class="row" onsubmit={add}>
    <input bind:value={text} placeholder="A note" aria-label="note" />
    <button class="primary" disabled={!text.trim()}>Add</button>
  </form>
  {#if error}<p class="error">{error}</p>{/if}
  {#if notes.length}
    <ul class="card">
      {#each notes as note (note.id)}
        <li class="row"><span>{note.text}</span><small class="end">{when(note.createdAt)}</small></li>
      {/each}
    </ul>
  {:else}
    <div class="empty"><p>No notes yet</p><p>Write one above: a line is enough.</p></div>
  {/if}
</main>
