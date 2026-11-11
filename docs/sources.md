# Sources: where apps, agents and tools come from

A **source** is a git repository Handler reads to offer things to install: apps, agents (to set
up in a project) and tools. Handler has its own, reviewed by its maintainer,
[handler-ai-registry](https://github.com/macray/handler-ai-registry): the Notes and Tracker
apps, agents (a marketer, a web designer…) and tools (GitHub, the Playwright and Lightpanda
browsers, toolchains such as Go, Java, Rust and Bun) come from it. You can add others: a
colleague's, a company's, your own.

## Installing from one

Each shelf of the **Library** has **Get more**: what the sources offer of its kind. Each card
says where it comes from (*from Handler*, or the source's name) and what it does in a few words
(in amber when it lets something reach more: a site, an image built on your computer). Its name
opens its page: what it is (its README), what it may do and what it needs from you, before
anything is installed.

| Kind | Where | On the command line |
|---|---|---|
| an app | **Library → Apps → Get more** → **Install** | `handler app add NAME --from SOURCE` |
| agents | **Library → Agents → Get more** → **Set up…** (or a project's ⋯ → **Get agents…**) | `handler project import-agents NAME --from SOURCE` |
| a tool | **Library → Tools → Get more** → **Install** | `handler tool add NAME` (`--from SOURCE` for one you added) |

Installing goes through the same page as for a file: an app's install page (what it may touch,
what it needs from you), the agents' set-up page (each one's model, what it will be allowed to
do; a tool they need that one of your sources offers comes with them, its hosts and what it adds
to the toolbox said there, and **Install … and set it up** installs it first; one that needs a
connection is installed and connected in Library → Tools first), a tool's preview (its hosts, secrets, programs, that its image is built on your
computer, and the system packages it adds to the toolbox, with their install scripts). Nothing is installed or updated by itself.

When a source holds a new version of something you installed from it, Handler offers it: **Get
it** in Library → Apps → Get more, *See the update* in a tool's ⋯. Agents set up from a source are yours: the
source changes nothing in them afterwards.

## Adding one

**Settings → Expert → Sources → Add a source**: its `https://` address. Handler reads it first: it must
have a `handler-source.toml` at its root. **Handler does not check what is in a source you
add**: what you install from it runs on your computer, within what its install page shows. Add
only one you trust; the dialog asks you to say so.

Each source is read again when you open a page listing it after a day, or with **Read again**.
**Remove** stops it offering anything; what you installed from it stays. Handler's own source
cannot be removed. On the command line: [`handler source`](cli/source.md).

## Making one

Any git repository laid out this way is a source:

```
handler-source.toml    apiVersion = "handler.source/v1"
                       name = "Acme tools"
                       description = "What Acme's team uses with Handler"
apps/<name>/           an app's code, as Export makes it: app.toml, server/, ui/dist/ built
agents/<name>/         an agents file's content (Export agents, unzipped): agents.toml, agents/
tools/<name>/          a tool: tool.toml, its Containerfile, skills/ (see Tools)
system-packages/<name>/  a system package its tools need: package.toml, install-fedora.sh,
                       check.sh; installed with the tool needing it, never alone
```

Each folder is named as what it holds (the `name` in its `app.toml`, `agents.toml` or
`tool.toml`), and may have a `README.md`: its page (a card's name, in Get more) shows it. Handler reads the last
commit of the default branch, and nothing else of the repository (its own README, CI files). A file that is a link, or a submodule, is never read: the item
holding one is not offered, and Settings → Expert → Sources says why.

See also: [apps](apps.md) · [tools](tools.md) · [concepts](concepts.md)
