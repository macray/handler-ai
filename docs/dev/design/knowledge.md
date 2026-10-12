# Knowledge vaults

Normative rules: `contracts.md` D.5. As users see it: [knowledge folders](../../user/knowledge.md).
Code: `packages/control-plane/src/handler_control/knowledge.py` (checks, mounts, listing).

What the folders hold, and how an agent reads them, is not Handler's concern: to Handler they
are folders of markdown to mount read-only. A skill can teach agents how to read them.

## One generic feature

Handler needs one generic feature: **read-only folders selected per agent**, the
same way bindings are selected. Knowledge follows the project (`projects/my_shopify_project`
matters for the theme repository, not elsewhere), and `me/` is simply selected with it.

- Folders come from one **knowledge root** and are named relative to it (an absolute path inside
  it works too). A single root keeps the choice safe (nothing outside it can be mounted, symlinks
  included) and lets the UI list what can be picked. The root: `HANDLER_KNOWLEDGE_DIR`, else the
  web UI's setting (`~/.config/handler-ai/knowledge.toml`), else `~/knowledge`.
- Each folder is mounted read-only at `/knowledge/<folder name>`. Refused: two folders with the
  same name, a folder inside another selected one, hidden folders.
- Knowledge folders are a setting of the agent, like `bindings`; the API takes them as
  `knowledge?: string[]` on the agent requests.
- A skill that teaches reading the folders is attached like any skill (the skill library).
- The Knowledge page only reads: notes are written elsewhere (an editor, Obsidian, a tool the
  user runs). A folder's `_index.md`, when there is one, is shown first.

## What Handler never does

No parsing, no indexing, and it never calls a model on its own initiative. Its one write: an
automation (contracts §I) may declare notes handlerd appends its script's output to, after a run
succeeded, with a comment saying where it came from (`knowledge.append_note`); knowledge stays
read-only to every sandbox.
