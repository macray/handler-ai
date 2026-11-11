"""Sources (D.26) for tests: a folder committed as a git repository; the made-up source the test
daemon reads as the official one (HANDLER_OFFICIAL_SOURCE); Handler's real registry, opt-in."""

import os
import shutil
from pathlib import Path

import pytest
from dulwich import porcelain

TEST_SOURCE = Path(__file__).resolve().parents[1] / "fixtures" / "source"
# A checkout of a registry of Handler's, for the tests of its items (Planner, shopify: in the
# private one only): opt-in, as it is not in this repository and changes without notice.
REGISTRY = Path(r) if (r := os.environ.get("HANDLER_TEST_REGISTRY")) else None


def requires_registry(item: str) -> pytest.MarkDecorator:
    """Skips unless HANDLER_TEST_REGISTRY holds `item` (`apps/planner`): the public registry
    holds neither Planner nor shopify."""
    if REGISTRY is None:
        return pytest.mark.skip(reason="HANDLER_TEST_REGISTRY not set")
    return pytest.mark.skipif(
        not (REGISTRY / item).is_dir(), reason=f"{item} is not in HANDLER_TEST_REGISTRY"
    )


def git_repo(folder: Path, target: Path) -> Path:
    """`folder`'s files (not its .git, nor node_modules) committed in a new repository."""
    target = target.resolve()
    shutil.copytree(
        folder, target, symlinks=True, ignore=shutil.ignore_patterns(".git", "node_modules")
    )
    with porcelain.init(str(target)) as repo:
        porcelain.add(repo, [str(p) for p in target.rglob("*") if ".git" not in p.parts])
        porcelain.commit(repo, b"source", author=b"t <t@t>", committer=b"t <t@t>")
    return target
