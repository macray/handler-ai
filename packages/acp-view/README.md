# acp-view — rendering of an ACP session

**Implements:** nothing on the wire; the view of a session shared by the two web apps that show
one: the Handler web UI (`packages/web-ui`) and the remote client (`packages/remote-client`).
**Depends on:** the ACP TypeScript SDK, marked, DOMPurify, diff. Svelte sources: each app
compiles them (no build of its own), and each app's Tailwind entry imports `theme.css` and
`@source`s this folder.

| Path | Role |
|---|---|
| `src/lib/connection.svelte.ts` | one attachment to a daemon-held session (F.4, F.7) over any `Transport` (the web UI's WebSocket, the remote client's encrypted mailbox): `session/load` replay, prompt, cancel, modes, options, permission requests (withdrawn when another client answered), `_handler/…` busy state |
| `src/lib/session.svelte.ts` | view model: `session/update` → messages, thoughts, tool calls, plan… |
| `src/lib/tools.ts` | a tool call in one line (its verb, paths relative to the session's folder, what it gave back), the step in progress, a turn's footer |
| `src/lib/diff.ts` | a file's change as rows: numbered lines, a replaced line's changed words, unchanged runs folded |
| `src/lib/follow.ts` | the timeline kept at its end while the user is there (the page's "↓ Latest" when not) |
| `src/lib/render.ts` | **untrusted agent output**: markdown without raw HTML, safe URLs only, DOMPurify |
| `src/components/` | Timeline, ToolCall, Diff, Plan (the current plan, pinned by a page that wants it), Composer, PermissionPrompt — plain Svelte + theme tokens, no shadcn |
| `src/theme.css` | the Handler look: tokens (light / `.dark`), markdown styles, `.term-surface` (the always-dark terminal) |

Tests: the sanitizer and view model are tested in `packages/web-ui/tests` (vitest); both apps in
real browsers in `tests/e2e`.
