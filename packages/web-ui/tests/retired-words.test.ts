// One name per thing (E8 §4): the words retired from what the web UI and the phone client show,
// each with the one that replaced it. Reads both packages' sources (Vite's `import.meta.glob`), comments left out
// (and the generated contracts), so that only strings and markup text can match; the phrases are
// matched case-sensitively, as whole words, so an identifier (`toggleRemote`, `class Remote`)
// never does.
import { describe, expect, it } from "vitest";

const RETIRED: { words: RegExp; use: string }[] = [
  // an app's own folder
  { words: /\b[Ww]here it keeps your files\b/, use: "<App>'s folder (Planner's folder)" },
  { words: /\b[Ww]here your \w+ is kept\b/, use: "<App>'s folder (Planner's folder)" },
  { words: /\b[Tt]he folder for \$?\{?\w/, use: "<App>'s folder, or its folder <name>" },
  // allowing a refused host after a run
  { words: /\bAllow and run again\b/, use: "Allow <host> for <agent>, run again from step N (lib/hosts.ts allowAgain)" },
  { words: /\bAllow it and run again\b/, use: "Allow <host> for <agent>, run again from step N (lib/hosts.ts allowAgain)" },
  // sharing a session with the phone
  { words: /\bRemote switch\b/, use: "On your phone (the phone icon in a session's header)" },
  { words: /\bRemote settings\b/, use: "Settings → Your phone" },
  { words: /(["'`>]\s*)Remote(\s*["'`<])/, use: "On your phone" },
  // who an agent runs as
  { words: /\b[Ww]hat it runs on\b/, use: "Who works (account · program · model)" },
  { words: /\baccount or provider, and model\b/, use: "Who works: account, program and model" },
  // the Library's other list, beside Yours
  { words: /\bGet more\b/, use: "Community (Library → <shelf> → Community)" },
];

// both packages' sources as text (Vite reads them), the generated contracts left out
const SOURCES: Record<string, string> = import.meta.glob(
  ["../src/**/*.{svelte,ts}", "../../remote-client/src/**/*.{svelte,ts}", "!**/contracts.gen.ts", "!**/remote.gen.ts", "!**/*.d.ts"],
  { query: "?raw", import: "default", eager: true },
);

/** The source without its comments (HTML ones, block ones, and `//` ones that start a line or
 *  follow a space: not a URL's), each replaced by as many newlines, so line numbers hold. */
export function uncommented(text: string): string {
  const blank = (m: string) => m.replace(/[^\n]/g, "");
  return text
    .replace(/<!--[\s\S]*?-->/g, blank)
    .replace(/\/\*[\s\S]*?\*\//g, blank)
    .replace(/(^|\s)\/\/[^\n]*/g, (_, before: string) => before);
}

describe("retired words", () => {
  it("strips comments, not strings", () => {
    expect(uncommented('a("x") // Remote switch\n/* what it runs on */ b(">Remote<")')).toBe('a("x") \n b(">Remote<")');
    expect(uncommented('href="https://x.y/"')).toBe('href="https://x.y/"');
  });

  it("the patterns match the words, not identifiers", () => {
    const remote = RETIRED.find((r) => r.use === "On your phone")!.words;
    expect(remote.test('aria-label="Remote"')).toBe(true);
    expect(remote.test("<b>Remote</b>")).toBe(true);
    expect(remote.test("class Remote {")).toBe(false);
    expect(remote.test("onclick={toggleRemote}")).toBe(false);
  });

  const all = Object.entries(SOURCES);
  it("reads both packages' sources, not the generated ones", () => {
    expect(all.some(([f]) => f.includes("remote-client/src/"))).toBe(true);
    expect(all.some(([f]) => f.endsWith(".gen.ts"))).toBe(false);
    expect(all.length).toBeGreaterThan(50);
  });

  for (const { words, use } of RETIRED) {
    it(`no "${words.source}" (say: ${use})`, () => {
      const found: string[] = [];
      for (const [file, text] of all) {
        uncommented(text)
          .split("\n")
          .forEach((line, i) => words.test(line) && found.push(`${file.replace(/^(\.\.\/)+/, "")}:${i + 1}: ${line.trim()}`));
      }
      expect(found, `retired; say ${use}`).toEqual([]);
    });
  }
});
