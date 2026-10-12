# handler knowledge

List the knowledge folders an agent can get.

## When to use it

To find the names `--knowledge FOLDER` takes. An agent sees each folder it gets read-only at
`/knowledge/<name>`: your notes, a team's documentation.

## Usage

```
handler knowledge list
```

## Output

The knowledge root (set in the web UI) and its folders. FOLDER is a path relative to the root, or
an absolute path inside it.

## See also

[knowledge folders](../knowledge.md) · [agent options](agent-options.md#what-it-gets)
