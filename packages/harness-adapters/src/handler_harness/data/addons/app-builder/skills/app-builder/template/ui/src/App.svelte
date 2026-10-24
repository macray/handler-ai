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

  $effect(() => {
    void run(() => api<Note[]>("notes"));
  });
</script>

<main>
  <h1>Notes</h1>
  <form onsubmit={add}>
    <input bind:value={text} placeholder="A note" aria-label="note" />
    <button disabled={!text.trim()}>Add</button>
  </form>
  {#if error}<p class="error">{error}</p>{/if}
  <ul>
    {#each notes as note (note.id)}
      <li>{note.text} <small>{new Date(note.createdAt).toLocaleString()}</small></li>
    {:else}
      <li class="empty">No notes yet.</li>
    {/each}
  </ul>
</main>
