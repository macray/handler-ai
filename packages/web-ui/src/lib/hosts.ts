import type { EgressEvent } from "./contracts.gen";

// Allow-list entries typed in the web UI (A.3). The daemon validates them again; these checks only
// give earlier feedback.

const HOST = /^(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;
const OCTET = "(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)";
const IPV4 = new RegExp(`^(${OCTET}\\.){3}${OCTET}$`);
const PORT = /^([1-9]\d{0,3}|[1-5]\d{4}|6[0-4]\d{3}|65[0-4]\d\d|655[0-2]\d|6553[0-5])$/;

/** An allow-list entry (A.3): `HOST:PORT`, HOST `example.com`, `*.example.com` or an IPv4
 *  address, and the port always written out (443 for https, 80 for http): no default. */
export function isEgressEntry(entry: string): boolean {
  const i = entry.lastIndexOf(":");
  if (i < 0) return false;
  const host = entry.slice(0, i);
  return PORT.test(entry.slice(i + 1)) && (HOST.test(host) || IPV4.test(host));
}

/** What the user typed as an allow-list entry: trimmed, lowercased, without a scheme or path.
 *  The port is kept as typed, never inferred from the scheme. */
export function normalizeEntry(input: string): string {
  return input
    .trim()
    .toLowerCase()
    .replace(/^[a-z]+:\/\//, "")
    .replace(/[/?#].*$/, "");
}

/** `list` with `entry` added (sorted, no duplicates), as the daemon writes it. */
export function withEntry(list: readonly string[], entry: string): string[] {
  return [...new Set([...list, entry])].sort();
}

/** An agent's own hosts (A.3): those it is allowed, those the person keeps blocked; a host is
 *  in one at most. */
export type OwnHosts = { allow: string[]; blocked: string[] };

/** `hosts` with its list `list` set to `next`: the hosts saved in it taken off the other. */
export function withList(hosts: OwnHosts, list: keyof OwnHosts, next: string[]): OwnHosts {
  const off = (other: string[]) => other.filter((h) => !next.includes(h));
  return list === "allow" ? { allow: next, blocked: off(hosts.blocked) } : { allow: off(hosts.allow), blocked: next };
}

/** One line of the network panel's recent connections (A.3): what became of a request. */
export type Outcome = "reached" | "could not connect" | "blocked" | "kept blocked" | "allowed" | "would be blocked" | "held" | "secret added" | "secret blocked";

export interface RecentLine {
  host: string;
  outcome: Outcome;
  detail?: string; // could not connect: why; a secret's name
}

/** The filter's last events as lines, newest first: a connection let through says whether the
 *  host was reached or could not be (its error), a refused one whether the person keeps it
 *  blocked (`blocked`, their current list). An `allowed` decision is shown only until its
 *  connection's outcome comes. */
export function recentLines(events: readonly EgressEvent[], blocked: readonly string[], count = 15): RecentLine[] {
  const lines: RecentLine[] = [];
  events.forEach((e, i) => {
    const later = events.slice(i + 1);
    switch (e.decision) {
      case "reached":
        return lines.push({ host: e.host, outcome: "reached" });
      case "unreached":
        return lines.push({ host: e.host, outcome: "could not connect", detail: e.error ?? undefined });
      case "denied":
        return lines.push({ host: e.host, outcome: blocked.includes(e.host) ? "kept blocked" : "blocked" });
      case "allowed":
        if (later.some((o) => o.host === e.host && (o.decision === "reached" || o.decision === "unreached"))) return;
        return lines.push({ host: e.host, outcome: "allowed" });
      case "unlisted":
        return lines.push({ host: e.host, outcome: "would be blocked" });
      case "held":
        return lines.push({ host: e.host, outcome: "held" });
      case "injected":
        return lines.push({ host: e.host, outcome: "secret added", detail: e.secret ?? undefined });
      case "leak":
        return lines.push({ host: e.host, outcome: "secret blocked", detail: e.secret ?? undefined });
    }
  });
  return lines.slice(-count).reverse();
}
