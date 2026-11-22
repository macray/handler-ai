// The inbox's messages for the bell: its unread ones that failed or want an answer (a run, a plan
// stopped, hosts refused) or an app's open nudge (H.17: unread again at each of its reminders)
// wait for you. Read again on each change of the inbox (the event stream), for the bell and the
// inbox page alike.
import { api } from "./api";
import { onChange } from "./events.svelte";
import type { InboxMessage } from "./contracts.gen";
import { waitsForYou } from "./nudges";

class InboxCount {
  unread = $state(0);
  messages = $state<InboxMessage[]>([]);
  private following = false;

  /** Counted now and on each change (once, whoever asks). */
  start(): void {
    if (this.following) return;
    this.following = true;
    onChange(["inbox"], () => void this.refresh());
    void this.refresh();
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

  /** What waits for you here (`waitsForYou`), newest first. */
  get waiting(): InboxMessage[] {
    return this.messages.filter(waitsForYou).sort((a, b) => b.at.localeCompare(a.at));
  }
}

export const inbox = new InboxCount();
