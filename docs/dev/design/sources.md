# Sources

Where apps, agents and addons come from: git repositories Handler reads to offer them, its own
official one and any the person adds. Normative: [contracts §D.26](../contracts.md) (and G.5 for
addons, H.13 for apps, D.23 for agents). The UI says *source*, *Add a source*, *from Handler*;
the code says the same (`sources.py`, `Source`, `/v1/sources`).

## Why

Each kind had its own answer to "where does this come from": addons from a catalog in Handler's
package, a folder or an archive URL; apps from Handler's package (Planner) or a file; agents from
a file only. Sharing with someone meant sending a file, and getting a new addon or app from
Handler meant a new Handler release. Every kind already had an install page that is the real
gate (what it may touch, what it needs, what it runs); what was missing was a place to get things
from that can change over time, that a team or a person can publish to, and that Handler itself
uses.

A git repository is that place: people already publish and review there (pull requests), it
keeps history, and a forge serves it to anyone. Handler's own things moved there too, so there is
one answer for everything: a source.

## Choices

- **A source only offers.** It never installs or updates anything: installing is each kind's own
  path and page, unchanged, saying where the thing comes from. An update is offered, never
  applied (a newer app is deployed by the person, an addon's update shows its preview again).
- **The person's trust, said once.** Handler cannot vouch for a repository it does not review.
  Adding one says so plainly and asks the person to tick that they trust it; each card then says
  where it comes from. Not asked again on every install: the install pages already show what each
  thing may do, which is the real decision.
- **The official source is Handler's, reviewed by its maintainer.** It replaced the catalogs in
  Handler's package (the addons `shopify` and `playwright`, the app Planner). It is its own
  repository (GitHub), read by every Handler, not part of Handler's: Handler's tests read a
  made-up source (`tests/fixtures/source/`), and those of its real items (Planner, shopify) run
  against a checkout of it when `HANDLER_TEST_REGISTRY` names one. It releases apart from
  Handler: a new addon or a fixed app needs no new Handler. `HANDLER_OFFICIAL_SOURCE` points
  Handler at a local clone, to try a change before publishing.
- **The folders are the index.** `apps/<name>/`, `agents/<name>/`, `addons/<name>/`, each in
  the format people already exchange as files (an app's export, an agents file unzipped, an addon
  folder), plus a small `handler-source.toml` naming the source. No list to keep in sync with
  the folders; an author tries an item with the file-based command before publishing it.
- **Read without running anything.** dulwich (pure Python, already a dependency) makes a shallow,
  bare clone: no hooks, filters, submodules or LFS, no `git` needed on the person's computer
  (Handler is not only for developers), none of the host's git configuration or credential
  helpers involved. The files are then written out from the commit's tree by Handler itself:
  only the three folders and the manifest, never a link (an item holding one is not offered),
  with limits on count and size.
- **Read when it matters.** When added, when a page lists it after a day, or on *Read again*;
  never in the background. A failed read keeps what was read before, beside its error.
- **One shelf, and short lists where things are used.** *Discover* (first in the menu's
  library) lists everything the sources offer, by kind (apps, agents, tools for agents), with a
  search and filters for kind and source; each card says where it comes from and, in a few words
  from its manifest, what it does (what weakens the sandbox first, in amber). An item's page
  shows its README and what it may do and needs, before anything is installed: a person who
  cannot read code decides from that, and the install page says it again. The Apps page, the
  addon installer and a project's *Add agents from a source* keep a short list of their kind,
  ending in *See all in Discover*: the choice is often made where the need is. Discover sorts by
  kind, not by source (sources are a detail once trusted) nor by use (categories need more items
  than there are, and words in each manifest to keep them). Settings → Sources manages them.
  (2026-10-22: first no Discover page, then this, after mockups of three layouts.)
- **Removing a source keeps what came from it.** What was installed is the person's.
- **No compatibility field.** An item this Handler cannot read (a newer manifest) is listed with
  its error and not offered; a field saying which Handler an item needs would say the same thing
  twice.

## Not built yet

Private repositories (a token per source); choosing a branch or a tag; skills as a fourth kind
(they travel inside agents); Discover by use (*Your days*, *A shop*…: a `uses` list in each
manifest) once there are enough items; an icon per item; signing (an item's next version signed
by the same key as the first); a directory of everyone's sources (search, ratings, reports);
publishing from Handler (a pull request to a source).
