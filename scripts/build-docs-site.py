#!/usr/bin/env python3
"""Build the documentation website (zensical.toml, published on GitHub Pages by
.github/workflows/docs.yml) from the Markdown read on GitHub: README.md and docs/, gathered into
docs-site/src (README.md becoming the home page, with branding/ for its logo; the images in docs/
next to their pages), then built with Zensical into docs-site/site. docs-site/ is ignored.

A link to a file of the repository that is not a page (code, another project's README) is
rewritten to that file on GitHub (repo_url in zensical.toml). A link to a path that is
not in the repository is left as is, and the strict build stops on it.

    scripts/build-docs-site.py          # build, stop on any warning
    scripts/build-docs-site.py serve    # preview on http://localhost:8000
"""

import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ZENSICAL = "zensical==0.0.69"
REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "docs-site" / "src"

# a Markdown link's target: [text](target) or [text](target "title")
LINK = re.compile(r"(\]\()([^)\s]+)")


def pages() -> dict[Path, Path]:
    """Each page's (or image's) path in the repository → its path in the site."""
    found = {Path("README.md"): Path("index.md")}
    for page in sorted((REPO / "docs").rglob("*")):
        if page.is_file():
            path = page.relative_to(REPO)
            found[path] = path
    return found


def rewrite(text: str, page: Path, site: dict[Path, Path], repo_url: str) -> str:
    """Point page's relative links at the site's pages, or at the repository on GitHub."""

    def target(match: re.Match[str]) -> str:
        url = match[2]
        if re.match(r"[a-z]+:|#|/", url):
            return match[0]
        path, _, anchor = url.partition("#")
        resolved = Path(os.path.normpath(page.parent / path))
        if resolved in site:
            new = Path(*[".."] * len(site[page].parent.parts), site[resolved])
        elif (REPO / resolved).exists():
            kind = "tree" if (REPO / resolved).is_dir() else "blob"
            new = f"{repo_url}/{kind}/HEAD/{resolved}"
        else:
            return match[0]
        return f"{match[1]}{new}{'#' + anchor if anchor else ''}"

    # code blocks are left as they are: a link there is an example
    parts = re.split(r"(^```.*?^```)", text, flags=re.M | re.S)
    return "".join(p if p.startswith("```") else LINK.sub(target, p) for p in parts)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "build"
    if mode not in ("build", "serve"):
        sys.exit(__doc__)
    config = REPO / "zensical.toml"
    repo_url = tomllib.loads(config.read_text())["project"]["repo_url"].rstrip("/")
    site = pages()
    shutil.rmtree(SRC, ignore_errors=True)
    for page, dest in site.items():
        (SRC / dest).parent.mkdir(parents=True, exist_ok=True)
        if page.suffix == ".md":
            (SRC / dest).write_text(rewrite((REPO / page).read_text(), page, site, repo_url))
        else:
            shutil.copy2(REPO / page, SRC / dest)
    shutil.copytree(REPO / "branding", SRC / "branding")
    command = ["uvx", "--from", ZENSICAL, "zensical", mode, "-f", str(config)]
    sys.exit(subprocess.call([*command, "--strict"] if mode == "build" else command))


if __name__ == "__main__":
    main()
