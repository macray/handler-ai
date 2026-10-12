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
