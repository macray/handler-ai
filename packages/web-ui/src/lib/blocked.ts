// Why a page's or a card's main action is disabled, and its fix (E1): a short sentence beside the
// button, the fix one click away where the person is. Only for main actions: a small button says
// it in its tooltip, a plain form check says nothing. The reason is neutral (a missing step is not
// a risk). Where the only missing thing is a choice, the button becomes the choice instead.
import { chosen } from "./access";
import type { ConnectKind } from "./connect.svelte";
import type { AccountInfo, AddonInfo, AgentDefinition, HarnessInfo } from "./contracts.gen";
import { href } from "./router.svelte";
import { toolsAsked, type Choice } from "./setup";

/** The fix: a page to go to (`href`), a Connect dialog over this page (`connect`, lib/connect),
 *  or a control on this page to bring into view and focus (`focus`, a CSS selector: its element,
 *  or the first control inside it), clicked when `open` (a picker opens). Not found on the page,
 *  `href` is where it goes instead. */
export type Fix = { label: string; href?: string; connect?: ConnectKind; focus?: string; open?: boolean };

/** `reason`, then `what` in the text's colour (what is still to choose), then the fix. */
export type Blocked = { reason: string; what?: string; fix?: Fix };

const MODELS = href({ view: "settings", section: "models" });

/** A helper's Turn on (D.18), from what it still needs: a tool to install first, then who
 *  works (its picker, `picker`, opened; with nothing connected, Model access), then a
 *  connection to a tool, then a notes folder. Null: nothing missing. */
export function helperBlocked(d: AgentDefinition, c: Choice, addons: AddonInfo[], picker: string): Blocked | null {
  const install = toolsAsked(d.addons ?? [], addons).install;
  if (install.length) return { reason: `Install the ${install[0]} tool first`, fix: { label: "Library → Tools", href: href({ view: "library", shelf: "tools", more: true }) } };
  if (!chosen(c.model, d.modelAlone ?? false)) return { reason: "Choose who works first", fix: { label: "Choose", focus: picker, open: true, href: MODELS } };
  const bound = Object.entries(c.bindings).find(([, b]) => !b);
  if (bound) return { reason: `Connect the ${bound[0]} tool first`, fix: { label: "Library → Tools", href: href({ view: "library", shelf: "tools" }) } };
  const notes = Object.entries(c.knowledge).find(([, k]) => !k);
  if (notes) return { reason: `It needs a notes folder for ${notes[0]}` };
  return null;
}

/** Settings → Your phone's Pair a device, with no gateway yet: its step 1, above. */
export const PAIR_BLOCKED: Blocked = { reason: "Connect your gateway first", fix: { label: "Step 1 ↑", focus: "#gateway-url" } };

/** No model connected: its Connect, over the page (Apps empty, lib/menu emptyFor). */
export const NO_MODEL: Blocked = { reason: "Connect a model first", fix: { label: "Connect…", connect: "both" } };

/** One thing an install page still asks (`text`) and the step where it is chosen (`at`, a
 *  selector). */
export type Todo = { text: string; at: string };

/** An app's Install (H.14), from what is still to choose: all of it said, Choose goes to the
 *  first. Null: nothing left. */
export function installBlocked(todo: Todo[]): Blocked | null {
  if (!todo.length) return null;
  return { reason: "Still to choose:", what: todo.map((t) => t.text).join(", "), fix: { label: "Choose", focus: todo[0]!.at } };
}

/** An app's suggested automation (H.1) whose agent would run on an account its harness's login
 *  refuses for runs nobody follows (I.7: the verdict that refuses turning it on): its switch on
 *  the install page stays off, saying why; the fix is Who works (`picker`, opened). Null: that
 *  model can run it. */
export function unattendedBlocked(
  model: { account?: string | null; harness?: string | null } | null | undefined,
  accounts: Pick<AccountInfo, "name" | "harness">[],
  harnesses: Pick<HarnessInfo, "name" | "login">[],
  picker: string,
): Blocked | null {
  const account = model?.account;
  if (!account) return null;
  const harness = accounts.find((a) => a.name === account)?.harness ?? model?.harness;
  if (harnesses.find((h) => h.name === harness)?.login?.unattended !== "refused") return null;
  return { reason: `${account}'s terms don't allow runs nobody follows`, fix: { label: "Choose an API key in Who works", focus: picker, open: true } };
}
