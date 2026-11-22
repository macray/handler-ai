# Notes

Notes your agents read: who you are, how a project works, what was decided; and, in a folder
you let it write, what an agent keeps for you. They are plain
markdown folders (*notes folders* on the command line) under one **notes root**, and an agent
reads the folders you select for it, never the others.

```
<notes root>/
├── me/                         how you work, your preferences
└── projects/
    └── my-theme/               this project's decisions and notes
```

## Where they are

There is nothing to set up: the notes root is `~/notes` until you change it, and Handler creates
it. **Library → Notes** shows it; **Change** makes another folder the
root, such as an Obsidian vault: type its full path (starting with `/` or `~/`), and the button
says what happens, **Use this folder** for one you have, **Create this folder** for a new one.
The shelf also creates folders and shows each folder's notes; links between notes work there. It
only reads: you write the notes. `HANDLER_NOTES_DIR` sets the root instead of the shelf.

## Give folders to an agent

In the agent's settings, pick the folders next to the tools (a folder covers its sub-folders), or
from the command line:

```bash
handler notes list                       # the root and the folders you can pick
cd ~/code/my-theme && handler run claude --notes me --notes projects/my-theme
```

Each folder appears in the agent's sandbox at `/notes/<folder name>`, **read-only**: the agent
does not change your notes. Two selected folders cannot have the same name, nor be inside one
another; hidden folders cannot be selected.

## Let an agent write a folder

An agent that keeps something for you (contacts, a reading log) needs to write. In its settings,
turn on **Can write** next to that folder (`--notes FOLDER=write` on the command line). It is
amber and asked again when you save, because it weakens the sandbox: the agent can then change
or delete **any file** of that folder, not only the ones it keeps, and its writes land in your
folder at once. Give it a folder of its own rather than your whole vault. The folder's `.git`
(a vault kept in git) stays read-only. The model alone (no program) only reads.

### See what changed, and undo it

Handler keeps a history of each folder an agent may write, apart from your notes and out of every
agent's reach: the folder as it was when you first gave it, then what changed, looked at every
five minutes and when Handler starts. In **Library → Notes**, open the folder: its **History**
lists each change, titled by the agents that could write then (with one agent writing the
folder, it is that one) and when, with its files and what changed in each ("added 2 lines under
Likes"). A folder you give an [app](apps.md) that writes it has the same history, in
your notes or not: on the app's page, under what you gave it, naming the app (and its jobs
writing there) when it could have made the change. Click a change to see its lines; **Undo this change**, under them, puts its files back as they were
before it. What the folder holds is kept first, so an undo can be undone too.

A link an agent makes in the folder is kept as a link: Handler never reads nor writes where it
points. A state that lasted less than five minutes may not be in the history, and a file over
64 MiB is not kept.

When a change leaves a document that does not follow its schema, your inbox says so; the file
stays as the agent wrote it.

## Documents of a known shape

A folder may hold documents of one kind (contacts, decisions), each a list of entries with the
same fields. A **schema** says that shape: add it in **Library → Schemas** (a `.schema.json`
file, `handler schema add`), then pick it in the agent's settings, **Schemas**, with **Writes**
on for an agent that keeps such documents (`--schema contacts@1=write`). The agent gets the
schema, read-only, and the built-in `knowledge` tool: the `handler-smd` command and a skill
that teaches it to write such documents, never inventing a value; it never adds a schema to your
Library itself. A schema is found by its `$id`
(`contacts@1`); a different one with the same `$id` is not taken without asking you. An
[app](apps.md#what-an-app-may-reach) may bring schemas too: they join your Library when you
install it.

The block at the top of a document, between its two `---` lines (its frontmatter), is yours:
when an agent changes the document's entries, or `handler-smd fmt` lays it out, that block stays
exactly as you wrote it, comments and layout included. An agent changes a value there only when
its task asks for it; if the block holds a comment, a name written twice or something that is
not valid YAML, that change is refused and the agent asks you to make it by hand, so nothing you
wrote there is lost.

## Help the agent read them

Folders say nothing by themselves about how to read them. A skill can: add it in **Library →
Skills** and pick it on the agents that read notes. When a folder has an `_index.md`
(its summary), Library → Notes shows it first.

## What writes to them

You, the agents you let write a folder, and the apps you give one to write (with their jobs).
Handler itself only when you undo a change from a
folder's history, and in one case you set up yourself: an [automation](automations.md) may add
what its script found to a note you name, once it succeeded, with a line saying where it came
from.

## See also

[`handler notes`](cli/notes.md)
