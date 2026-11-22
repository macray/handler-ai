// Connect a model from any page (E1): Connect a subscription, Connect an API key or local model,
// or both kinds on a first run, in a dialog over the page it is opened on (ConnectDialogs, mounted
// once in App), the same forms as Model access. The person stays on the page; whoever opened it
// (a Who works picker) is told what was connected, to choose it. One at a time: opening another
// drops the last one's `onDone`.

/** Which Connect: one kind, or both (a first run's "Connect a model"). */
export type ConnectKind = "both" | "account" | "provider";

/** What was connected: a new account (a subscription) or a new provider (an API, a local model). */
export type Connected = { kind: "account" | "provider"; name: string };

class Connecting {
  /** The Connect open, and who to tell; null: none. */
  current = $state<{ kind: ConnectKind; onDone?: (made: Connected) => void } | null>(null);
  /** Bumped each time an account or a provider is made: pages that list them load them again. */
  changes = $state(0);

  /** Open a Connect over the current page; `onDone` once one is made (even if its login is not
   *  finished: the opener chooses it only if it can run). */
  open(kind: ConnectKind, onDone?: (made: Connected) => void): void {
    this.current = { kind, onDone };
  }

  /** One was made: the dialog closes, its opener is told. */
  done(made: Connected): void {
    const onDone = this.current?.onDone;
    this.current = null;
    this.changes++;
    onDone?.(made);
  }

  /** Closed with nothing made. */
  close(): void {
    this.current = null;
  }
}

export const connect = new Connecting();
