// Remote control (docs/dev/design/remote.md, contract D.7) as the web UI sees it: the connector's
// status light, polled while the page is open, and the actions of Settings → Remote and of the
// session view's Remote switch. Views use only this module's interface (`remote`).
import { api } from "./api";
import type { RemotePairing, RemoteStatus } from "./contracts.gen";

export type RemoteLight = RemoteStatus["light"];

export const LIGHT_LABEL: Record<RemoteLight, string> = {
  off: "no gateway set",
  idle: "nothing shared",
  ok: "gateway reachable",
  unreachable: "gateway unreachable",
  unauthorized: "gateway refused the host token",
};

/** The dot's colour: green reachable, red unreachable, orange refused, grey not polling. */
export function lightTone(light: RemoteLight | undefined): string {
  if (light === "ok") return "bg-ok";
  if (light === "unreachable") return "bg-danger";
  if (light === "unauthorized") return "bg-warn";
  return "bg-muted-foreground/50";
}

class Remote {
  status = $state<RemoteStatus | null>(null);
  error = $state<string | null>(null);
  private timer: ReturnType<typeof setInterval> | null = null;

  /** Keep the status fresh (every 5 s) while the page is open. */
  start(): void {
    if (this.timer) return;
    void this.refresh();
    this.timer = setInterval(() => {
      if (!document.hidden) void this.refresh();
    }, 5_000);
  }

  async refresh(): Promise<void> {
    try {
      this.status = await api.remote();
      this.error = null;
    } catch (e) {
      this.error = (e as Error).message;
    }
  }

  get light(): RemoteLight | undefined {
    return this.status?.light;
  }

  shared(sessionId: string): boolean {
    return this.status?.sharedSessions?.includes(sessionId) ?? false;
  }

  async share(sessionId: string, enabled: boolean): Promise<void> {
    await api.shareSession(sessionId, enabled);
    await this.refresh();
  }

  async setGateway(url: string, token: string): Promise<void> {
    this.status = await api.setGateway(url.trim(), token.trim());
  }

  async clearGateway(): Promise<void> {
    this.status = await api.clearGateway();
  }

  async pair(name: string, person = "owner"): Promise<RemotePairing> {
    const pairing = await api.pairDevice(name.trim(), person);
    await this.refresh();
    return pairing;
  }

  async revoke(id: string): Promise<void> {
    await api.revokeDevice(id);
    await this.refresh();
  }
}

export const remote = new Remote();
