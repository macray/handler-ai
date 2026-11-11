// The inbox's messages for the bell: its unread ones that failed or want an answer (a run, a plan
// stopped, hosts refused) wait for you. Polled like the sessions, and set by the inbox page from
// the list it shows, so the two never disagree.
import { api } from "./api";
import type { InboxMessage } from "./contracts.gen";

const POLL_MS = 5000;

class InboxCount {
  unread = $state(0);
  messages = $state<InboxMessage[]>([]);
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
    this.messages = messages;
    this.unread = messages.filter((m) => !m.read).length;
  }

  /** What waits for you here: unread, failed or wanting an answer, newest first. */
  get waiting(): InboxMessage[] {
    return this.messages.filter((m) => !m.read && (m.status === "failed" || m.status === "attention")).sort((a, b) => b.at.localeCompare(a.at));
  }
}

export const inbox = new InboxCount();
