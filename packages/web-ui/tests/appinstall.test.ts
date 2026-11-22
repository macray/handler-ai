// An app's install page (E6): its folders offered from the work folders and your notes, and what
// is still to choose before Install.
import { describe, expect, it } from "vitest";
import { addedWords, canDoWords, folderSuggestions, jobLimits, needsProgram, startedByWords, stillToChoose } from "../src/lib/apps";
import type { AppFileNeed, AppJob } from "../src/lib/contracts.gen";

const entry = (root: string, name: string) => ({ name, path: `${root}/${name}` });
const planner = { name: "planner", title: "Planner" };

describe("the app's folder, suggested", () => {
  it("offers a new folder named after the app in the first work folder", () => {
    expect(folderSuggestions(planner, [{ path: "/home/me/notes/", entries: [entry("/home/me/notes", "blog")] }])).toEqual([{ path: "/home/me/notes/planner", isNew: true }]);
  });

  it("then the folders you have named after it (its name or its title), in any work folder", () => {
    const roots = [
      { path: "/home/me/code", entries: [entry("/home/me/code", "shop")] },
      { path: "/home/me/notes", entries: [entry("/home/me/notes", "Planner"), entry("/home/me/notes", "blog")] },
    ];
    expect(folderSuggestions(planner, roots)).toEqual([
      { path: "/home/me/code/planner", isNew: true },
      { path: "/home/me/notes/Planner", isNew: false },
    ]);
    const titled = { name: "reading", title: "Reading list" };
    expect(folderSuggestions(titled, [{ path: "/h/n", entries: [entry("/h/n", "reading-list")] }])).toContainEqual({ path: "/h/n/reading-list", isNew: false });
  });

  it("no new folder where one of its name is: that one is yours; none without a work folder", () => {
    expect(folderSuggestions(planner, [{ path: "/h/n", entries: [entry("/h/n", "planner")] }])).toEqual([{ path: "/h/n/planner", isNew: false }]);
    expect(folderSuggestions(planner, [])).toEqual([]);
  });

  // H.9: an app's folder may be in your notes; only suggestions, another folder can be picked
  const work = [{ path: "/h/code", entries: [entry("/h/code", "shop")] }];
  const notes = { path: "/h/notes", entries: [entry("/h/notes", "journal")] };

  it("offers a new folder in your notes too: last, or first when its data is notes", () => {
    expect(folderSuggestions(planner, work, { notes })).toEqual([
      { path: "/h/code/planner", isNew: true },
      { path: "/h/notes/planner", isNew: true, inNotes: true },
    ]);
    expect(folderSuggestions(planner, work, { notes, notesFirst: true })).toEqual([
      { path: "/h/notes/planner", isNew: true, inNotes: true },
      { path: "/h/code/planner", isNew: true },
    ]);
    const yours = { path: "/h/notes", entries: [entry("/h/notes", "Planner")] };
    expect(folderSuggestions(planner, [], { notes: yours })).toEqual([{ path: "/h/notes/Planner", isNew: false, inNotes: true }]);
  });

  it("its other folders: named after the app and the folder", () => {
    const cv = { name: "cv-assistant", title: "CV assistant" };
    const had = { path: "/h/notes", entries: [entry("/h/notes", "cv-assistant-cvs")] };
    expect(folderSuggestions(cv, work, { need: "cvs", notes: had, notesFirst: true })).toEqual([
      { path: "/h/notes/cv-assistant-cvs", isNew: false, inNotes: true },
      { path: "/h/code/cv-assistant-cvs", isNew: true },
    ]);
  });
});

describe("what is still to choose", () => {
  const data: AppFileNeed = { name: "tasks", mode: "rw" };
  const base = { title: "Planner", data, target: "", others: [], otherFolders: {}, secrets: [], given: {} };

  it("its folder, until one is chosen", () => {
    expect(stillToChoose(base)).toEqual([{ text: "Planner's folder", at: '[data-step="folder"]' }]);
    expect(stillToChoose({ ...base, target: "/h/n/planner" })).toEqual([]);
    expect(stillToChoose({ ...base, data: { ...data, path: "/h/n/planner" } })).toEqual([]);
  });

  it("its other folders and its secrets not given yet", () => {
    const more = { ...base, target: "/t", others: [{ name: "inbox", mode: "ro" as const }], secrets: [{ name: "TOKEN", set: false }, { name: "KEY", set: true }] };
    expect(stillToChoose(more).map((t) => t.text)).toEqual(["its folder inbox", "the secret TOKEN"]);
    expect(stillToChoose({ ...more, otherFolders: { inbox: "/i" }, given: { TOKEN: " x " } })).toEqual([]);
  });
});

describe("an app with jobs (H.2)", () => {
  const base = { title: "CV", data: { name: "cv", mode: "rw" as const, path: "/h/cv" }, target: "/h/cv", others: [], otherFolders: {}, secrets: [], given: {} };
  const write: AppJob = { name: "write", description: "Writes your CV", canDo: { files: { cv: "write", notes: "read" }, worksIn: ["cv"], schemas: [], egress: [] } };
  const ask: AppJob = { name: "ask", description: "Answers a question", canDo: {} };
  const app = { files: [{ name: "cv", mode: "rw" as const, path: "/h/cv", description: "Your work experience" }, { name: "notes", mode: "ro" as const, description: "Your notes." }], jobs: [write, ask] };

  it("asks who works on its jobs until chosen", () => {
    expect(stillToChoose({ ...base, jobs: true, who: null })).toEqual([{ text: "who works on its jobs", at: '[data-step="who-works"] [data-testid="model-choice-access"]' }]);
    expect(stillToChoose({ ...base, jobs: true, who: { program: "fake", account: "fake" } })).toEqual([]);
    expect(stillToChoose(base)).toEqual([]); // no job: nothing asked
  });

  it("says what a job can do, with the folders given", () => {
    expect(canDoWords(write, app)).toEqual(["reads and writes /h/cv, working in it", "reads your folder “Your notes”", "no network"]);
    expect(canDoWords({ canDo: { schemas: ["cv/role"], egress: ["api.example.com:443"] } }, app)).toEqual(["uses the notes formats cv/role", "reaches api.example.com:443"]);
    expect([needsProgram(write), needsProgram(ask)]).toEqual([true, false]);
  });

  it("greys the model alone when a job needs a program, a refusing subscription when an automation runs one", () => {
    expect(jobLimits([ask], false)).toEqual({ alone: null, unattended: null });
    expect(jobLimits([ask, write], true)).toEqual({
      alone: "“Writes your CV” reaches folders, schemas or hosts: it needs a program",
      unattended: "its terms refuse automations' runs",
    });
  });

  it("says what a version adds in sentences, its jobs' too", () => {
    const words = (line: string) => addedWords(line, app);
    expect(words("job write")).toBe("a new job, “Writes your CV”");
    expect(words("job write: file notes (write)")).toBe("its job “Writes your CV” reads and writes your folder “Your notes”");
    expect(words("job ask: egress api.example.com:443")).toBe("its job “Answers a question” reaches api.example.com:443");
    expect(words("job ask: schema cv/role")).toBe("its job “Answers a question” uses the notes format cv/role");
    expect(words("job gone")).toBe("a new job, gone");
    expect(words("file cv (rw)")).toBe("reads and writes /h/cv");
    expect(words("egress x.org:443")).toBe("reaches x.org:443");
    expect(words("secret TOKEN")).toBe("gets the secret TOKEN");
    expect(words("notifications")).toBe("sends you notifications");
  });

  it("says what started a run", () => {
    expect(startedByWords({ startedBy: { by: "action", action: "write", via: "ask" } })).toBe("Ask");
    expect(startedByWords({ startedBy: { by: "action", action: "write", via: "nudge" } })).toBe("a nudge");
    expect(startedByWords({ startedBy: { by: "automation", automation: "weekly" } })).toBe("the automation weekly");
    expect(startedByWords({ startedBy: { by: "code" } })).toBe("its code");
  });
});
