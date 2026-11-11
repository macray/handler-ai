// Words made from values, the same on every page: sizes, slugs, names not taken yet.
// Pure string work, no DOM: unit-tested in tests/logic.test.ts.

/** A size as the disk counts it: "512 B", "2.0 MB", "143 MB", "1.2 GB". */
export function formatBytes(n: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1000 && i < units.length - 1) (n /= 1000), i++;
  return `${i === 0 || n >= 100 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

/** Lowercase letters and digits, the rest one "-": "Daily news digest!" → "daily-news-digest". */
export function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

/** `base`, else `base-2`, `base-3`… (with `sep`), the first not in `taken`, case aside. */
export function freeName(base: string, taken: string[], sep = "-"): string {
  const used = new Set(taken.map((t) => t.toLowerCase()));
  let name = base;
  for (let i = 2; used.has(name.toLowerCase()); i++) name = `${base}${sep}${i}`;
  return name;
}
