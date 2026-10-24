# Sources: where apps, agents and addons come from

A **source** is a git repository Handler reads to offer things to install: apps, agents (to set
up in a project) and addons. Handler has its own, reviewed by its maintainer: Planner, the
Shopify CLI and the Playwright browser come from it. You can add others: a colleague's, a
company's, your own.

## Installing from one

**Discover** (in the menu, above Skills) shows everything the sources offer: apps, agents, and
tools for your agents. Each card says where it comes from (*from Handler*, or the source's name)
and what it does in a few words (in amber when it lets something reach more: a site, an image
built on your computer). Its name opens its page: what it is (its README), what it may do and
what it needs from you, before anything is installed. The same things are also offered where you
use them, a few at a time:

| Kind | Where | On the command line |
|---|---|---|
| an app | **Apps** → *Start with one* / *Get more* → **Install** | `handler app add NAME --from SOURCE` |
| agents | a project's page → **Add agents from a source** | `handler project import-agents NAME --from SOURCE` |
| an addon | **Library → Addons** → **Install an addon** | `handler addon add NAME` (`--from SOURCE` for one you added) |

Installing goes through the same page as for a file: an app's install page (what it may touch,
what it needs from you), the agents' set-up page (each one's model, what it will be allowed to
do), an addon's preview (its hosts, secrets, programs, and that its image is built on your
computer). Nothing is installed or updated by itself.

When a source holds a new version of something you installed from it, Handler offers it: **Get
it** on the Apps page, *update available* on an addon. Agents set up from a source are yours: the
source changes nothing in them afterwards.

## Adding one

**Settings → Sources → Add a source**: its `https://` address. Handler reads it first: it must
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
addons/<name>/         an addon: addon.toml, its Containerfile, skills/ (see Addons)
```

Each folder is named as what it holds (the `name` in its `app.toml`, `agents.toml` or
`addon.toml`), and may have a `README.md`: its page in Discover shows it. Handler reads the last
commit of the default branch, and nothing else of the repository (its own README, CI files). A file that is a link, or a submodule, is never read: the item
holding one is not offered, and Settings → Sources says why.

See also: [apps](apps.md) · [addons](addons.md) · [concepts](concepts.md)
