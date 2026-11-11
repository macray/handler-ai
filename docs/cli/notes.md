# handler notes

List the notes folders an agent can get.

## When to use it

To find the names `--notes FOLDER` takes. An agent sees each folder it gets read-only at
`/notes/<name>`: your notes, a team's documentation.

## Usage

```
handler notes list
```

## Output

The notes root, where its setting comes from (`default`: `~/.local/share/handler-ai/notes`;
`config`: chosen in the web UI, Library → Notes → *Change*; `env`: `HANDLER_NOTES_DIR`), and its
folders. FOLDER is a path relative to the root, or an absolute path inside it.

## See also

[notes folders](../notes.md) · [agent options](agent-options.md#what-it-gets)
