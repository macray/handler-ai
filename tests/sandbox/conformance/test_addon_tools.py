"""Contract A.1 and A.7 conformance, every runtime: an addon's image extracted into a folder
(`image extract`), that folder mounted read-only (an addon's tools), appended to PATH."""

import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ...support.runtimes import Runtime
from ..conftest import CURL_IMAGE, run, spec

ADDON_TARGET = "/opt/tools/handler-test"


def build_addon(runtime: Runtime, directory: Path) -> str:
    """A tiny addon image, built through the runtime (A.7), FROM scratch, the installed tree as
    addons ship it (G.1): `bin/handler-hello`, a `bin/ls` that must not win over the image's, a
    version file. Its id."""
    (directory / "bin").mkdir(parents=True, exist_ok=True)
    (directory / "bin" / "handler-hello").write_text("#!/bin/sh\necho hello from the addon\n")
    (directory / "bin" / "ls").write_text("#!/bin/sh\necho addon-ls\n")
    for f in (directory / "bin").iterdir():
        f.chmod(0o755)
    (directory / "version").write_text(f"1 {uuid.uuid4()}\n")  # an image of its own per test
    (directory / "Containerfile").write_text("FROM scratch\nCOPY bin /bin\nCOPY version /version\n")
    id_file = directory / "iid"
    image = [runtime.binary, "image"]
    subprocess.run([*image, "build", str(directory), "--id-file", str(id_file)], check=True)
    return id_file.read_text().strip()


@pytest.fixture
def addon_image(runtime: Runtime, tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    image_id = build_addon(runtime, tmp_path_factory.mktemp("addon"))
    yield image_id
    subprocess.run([runtime.binary, "image", "remove", image_id], capture_output=True, check=False)


def extract(runtime: Runtime, image: str, path: str, folder: Path) -> subprocess.CompletedProcess:
    argv = [runtime.binary, "image", "extract", image, path, str(folder)]
    return subprocess.run(argv, capture_output=True, text=True, check=False)


@pytest.mark.rule("runtime.reads-an-image-without-running-it")
def test_an_image_s_folder_is_extracted(runtime: Runtime, addon_image: str, tmp_path: Path) -> None:
    """Its files, the host user's, without running anything (the image has no shell): the whole
    image (what Handler extracts), or one of its folders."""
    folder = tmp_path / "tools"
    r = extract(runtime, addon_image, "/", folder)
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in folder.iterdir()) == ["bin", "version"]
    assert (folder / "version").read_text().startswith("1 ")
    assert (folder / "bin" / "handler-hello").stat().st_mode & 0o111
    again = extract(runtime, addon_image, "/", folder)
    assert again.returncode == 1 and "exists" in again.stderr  # never over another folder
    assert extract(runtime, addon_image, "/bin", tmp_path / "bin").returncode == 0
    assert sorted(p.name for p in (tmp_path / "bin").iterdir()) == ["handler-hello", "ls"]
    missing = extract(runtime, addon_image, "/opt/nothing-here", tmp_path / "none")
    assert missing.returncode == 1 and not (tmp_path / "none").exists()


@pytest.mark.rule("runtime.reads-an-image-without-running-it")
def test_an_extracted_folder_has_none_of_what_later_layers_removed(
    runtime: Runtime, tmp_path: Path
) -> None:
    """An image whose later layers remove a file, and the whole folder before making it again
    (an install script replacing what an earlier one put): extracted, the folder holds what the
    image has, as built by the runtime's own builder (its whiteouts). If this fails: an addon's
    folder keeps files its image removed."""
    context = tmp_path / "context"
    context.mkdir()
    (context / "Containerfile").write_text(
        f"FROM {CURL_IMAGE}\nUSER root\n"
        "RUN mkdir -p /opt/t/sub /opt/u && touch /opt/t/old /opt/t/sub/old /opt/u/a /opt/u/b\n"
        "RUN rm -rf /opt/t /opt/u/a\n"  # its own layer: the folder's whiteout, not its files'
        "RUN mkdir -p /opt/t && touch /opt/t/new\n"
    )
    id_file = tmp_path / "iid"
    image = [runtime.binary, "image"]
    subprocess.run([*image, "build", str(context), "--id-file", str(id_file)], check=True)
    image_id = id_file.read_text().strip()
    try:
        assert extract(runtime, image_id, "/opt/t", tmp_path / "t").returncode == 0
        assert extract(runtime, image_id, "/opt/u", tmp_path / "u").returncode == 0
        assert [p.name for p in (tmp_path / "t").iterdir()] == ["new"]
        assert [p.name for p in (tmp_path / "u").iterdir()] == ["b"]
    finally:
        subprocess.run([*image, "remove", image_id], capture_output=True, check=False)


def with_addon(doc: dict[str, Any], folder: Path) -> dict[str, Any]:
    addon = {"source": str(folder), "target": ADDON_TARGET, "path": f"{ADDON_TARGET}/bin"}
    return doc | {"addons": [addon]}


@pytest.mark.rule("sandbox.read-only-stays-read-only")
def test_an_addon_s_folder_is_read_only_and_appended_to_path(
    runtime: Runtime, scope: Path, addon_image: str, tmp_path: Path
) -> None:
    folder = tmp_path / "tools"
    assert extract(runtime, addon_image, "/", folder).returncode == 0
    script = (
        "handler-hello; command -v ls;"
        f" echo x > {ADDON_TARGET}/x 2>/dev/null || echo ro-ok;"
        ' echo "$PATH"'
    )
    r = run(runtime.binary, with_addon(spec(scope, ["sh", "-c", script]), folder))
    hello, ls, ro, path = r.stdout.decode().splitlines()
    assert hello == "hello from the addon", r.stderr
    assert ls != f"{ADDON_TARGET}/bin/ls"  # the image's own commands win
    assert ro == "ro-ok"
    assert path.endswith(f":{ADDON_TARGET}/bin")
    assert path.split(":")[0] != f"{ADDON_TARGET}/bin"
    assert not (folder / "x").exists()
