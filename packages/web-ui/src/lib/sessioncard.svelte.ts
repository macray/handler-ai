// The open session's card: what it is, what it can reach and changed, its actions. The session
// page makes it (it holds that state) and hands it here; the sidebar shows it under the session's
// row in "Open sessions", or the session page shows it as a panel when the sidebar is hidden.
import type { Snippet } from "svelte";

class SessionCard {
  key = $state<string | null>(null); // the session it is the card of
  card = $state<Snippet | null>(null);

  show(key: string, card: Snippet): () => void {
    this.key = key;
    this.card = card;
    return () => {
      if (this.key !== key) return;
      this.key = null;
      this.card = null;
    };
  }
}

export const sessionCard = new SessionCard();
