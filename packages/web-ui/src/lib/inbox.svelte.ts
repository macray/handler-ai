// The inbox's unread messages, counted for the menu (its Inbox item): polled like the sessions,
// and set by the inbox page from the list it shows, so the two never disagree.
import { api } from "./api";
import type { InboxMessage } from "./contracts.gen";

const POLL_MS = 5000;

class InboxCount {
  unread = $state(0);
  private timer: ReturnType<typeof setInterval> | null = null;

  /** Counted now and every few seconds (once, whoever asks). */
  start(): void {
    if (this.timer) return;
    void this.refresh();
    this.timer = setInterval(() => void this.refresh(), POLL_MS);
  }

  async refresh(): Promise<void> {
    try {
      this.count(await api.inbox());
    } catch {
      /* the daemon is away: the count stays, next time */
    }
  }

  count(messages: InboxMessage[]): void {
    this.unread = messages.filter((m) => !m.read).length;
  }
}

export const inbox = new InboxCount();
