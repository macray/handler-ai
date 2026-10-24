// Drafts of an app's code (H.15): a session of the App creator (one of Handler's helpers, an
// agent with no folder) works on a copy of an app's code kept by Handler, or on an empty folder
// for a new app. One draft per app at a time. Used, its code becomes the app's next version
// (deployed at once when it may reach nothing more, else its page asks first), or a new app (its
// install page); thrown away, the session goes with it. Opened (H.16), the draft runs at its own
// address on copies, in a new tab, until it is used or thrown away.
import { api } from "./api";
import type { App, DraftCopy, Session } from "./contracts.gen";
import { navigate } from "./router.svelte";
import { sessions } from "./sessions.svelte";

/** A session of the App creator on a draft of `app` (none: a new app). Without one set up yet,
 *  its set-up page first. */
export async function startDraft(app?: string): Promise<void> {
  const creator = (await api.handlerNeeds()).find((r) => r.name === "app-creator");
  if (!creator?.agentId) {
    navigate({ view: "set-up-helper", need: "app-creator" });
    return;
  }
  const agent = await api.agent(creator.agentId);
  navigate({ view: "session", key: sessions.open(await api.createAppDraft(agent.id, app), agent).key });
}

/** The draft waiting for `app` (none: those of new apps), from a list of sessions. */
export function draftsOf(list: Session[], app: string | null): Session[] {
  return list.filter((s) => s.appDraft && (s.appDraft.app ?? null) === app);
}

/** Open a draft's session again. */
export async function continueDraft(s: Session): Promise<void> {
  navigate({ view: "session", key: sessions.open(s, await api.agent(s.agentId)).key });
}

/** Use it: a new app goes to its install page; the next version of one is deployed when it may
 *  reach nothing more than the one installed, else its page says what more and deploys it. */
export async function useDraft(sessionId: string): Promise<App> {
  const { app, added } = await api.useAppDraft(sessionId);
  const live = sessions.get(sessionId); // the session went with its draft
  if (live) await sessions.close(live);
  if (added) {
    navigate({ view: "install-app", name: app.name });
    return app;
  }
  const deployed = app.current && !app.source.addedNeeds?.length ? await api.deployApp(app.name) : app;
  navigate({ view: "apps", app: app.name });
  return deployed;
}

/** Open it in a new tab (opened at once, before handlerd answers: a tab opened later is
 *  blocked); what it works on instead of the real thing. */
export async function openDraft(sessionId: string): Promise<DraftCopy[]> {
  const tab = window.open("", "_blank");
  try {
    const opened = await api.openAppDraft(sessionId);
    if (tab) {
      tab.opener = null;
      tab.location.href = opened.url;
    }
    return opened.copies;
  } catch (e) {
    tab?.close();
    throw e;
  }
}

/** What an opened draft works on, in words: "its data: a copy (12 KB)". */
export function copyLabel(c: DraftCopy): string {
  const size = c.size == null ? "" : c.size < 1024 ? ` (${c.size} B)` : c.size < 2 ** 20 ? ` (${Math.round(c.size / 1024)} KB)` : ` (${Math.round(c.size / 2 ** 20)} MB)`;
  const how = c.how === "copy" ? `a copy${size}` : c.how === "read-only" ? "read only (too large to copy)" : "empty";
  return `${c.what}${c.path ? ` ${c.path}` : ""}: ${how}`;
}

/** Throw it away, once confirmed: the session and its folder go. */
export async function throwAway(s: Session): Promise<boolean> {
  if (!confirm(`Throw away this draft${s.appDraft?.app ? ` of ${s.appDraft.app}` : ""}? Its conversation and its code go; the app stays as it is.`)) return false;
  const live = sessions.get(s.id);
  if (live) await sessions.close(live); // off the menu first
  await api.deleteSession(s.id);
  return true;
}
