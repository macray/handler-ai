"""`image_archive.unpack`: an image's folder from an OCI archive, its layers' whiteouts applied.

Spec: contract A.7 (`extract`), the OCI image layer format (whiteouts, opaque folders). A real
image built and extracted on each runtime: tests/sandbox/conformance/test_addon_tools.py."""

import io
import json
import tarfile
from pathlib import Path

import pytest

from handler_sandbox_kit.image_archive import unpack

Layer = list[tuple[str, str | None]]  # (path, content): None makes a folder; "->x" a link to x


def _tar(entries: list[tuple[tarfile.TarInfo, bytes]]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        for info, data in entries:
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def _layer(entries: Layer) -> bytes:
    made = []
    for path, content in entries:
        info = tarfile.TarInfo(path)
        if content is None:
            info.type, info.mode = tarfile.DIRTYPE, 0o755
        elif content.startswith("->"):
            info.type, info.linkname = tarfile.SYMTYPE, content[2:]
        made.append(
            (info, b"" if content is None or content.startswith("->") else content.encode())
        )
    return _tar(made)


def archive(tmp_path: Path, *layers: Layer) -> Path:
    """An image archive as `image save` writes it (OCI layout), these layers first to last."""
    blobs: list[tuple[str, bytes]] = []

    def blob(data: bytes) -> str:
        digest = f"sha256:{len(blobs):064x}"  # unique; nothing here checks it
        blobs.append((digest, data))
        return digest

    manifest = {"layers": [{"digest": blob(_layer(layer))} for layer in layers]}
    index = {"manifests": [{"digest": blob(json.dumps(manifest).encode())}]}
    files = [(tarfile.TarInfo("index.json"), json.dumps(index).encode())]
    files += [(tarfile.TarInfo(f"blobs/{d.replace(':', '/')}"), data) for d, data in blobs]
    saved = tmp_path / "image.tar"
    saved.write_bytes(_tar(files))
    return saved


def tree(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


BASE: Layer = [
    ("opt", None), ("opt/t", None), ("opt/t/a", "a"), ("opt/t/b", "b"),
    ("opt/t/sub", None), ("opt/t/sub/old", "old"),
]  # fmt: skip


@pytest.mark.rule("runtime.reads-an-image-without-running-it")
@pytest.mark.parametrize(
    ("upper", "path", "left"),
    [
        pytest.param(
            [("opt/t/.wh.a", ""), ("opt/t/sub/.wh.old", "")], "/opt/t", ["b", "sub"], id="file"
        ),
        pytest.param([("opt/t/.wh.sub", "")], "/opt/t", ["a", "b"], id="folder-inside"),
        pytest.param(
            [("opt/.wh.t", ""), ("opt/t", None), ("opt/t/new", "n")],
            "/opt/t",
            ["new"],
            id="the-folder-itself-removed-then-made",
        ),
        pytest.param([("opt/.wh.t", "")], "/opt/t", [], id="the-folder-itself-removed"),
        pytest.param(
            [("opt/t", None), ("opt/t/new", "n"), ("opt/t/.wh..wh..opq", "")],
            "/opt/t",
            ["new"],
            id="opaque-listed-after-its-layer-s-files",
        ),
        pytest.param(
            [("opt", None), ("opt/.wh..wh..opq", ""), ("opt/t", None), ("opt/t/z", "z")],
            "/opt/t",
            ["z"],
            id="opaque-above-the-folder",
        ),
        pytest.param(
            [("opt/t/sub", None), ("opt/t/sub/.wh..wh..opq", ""), ("opt/t/sub/n", "n")],
            "/opt/t",
            ["a", "b", "sub", "sub/n"],
            id="opaque-inside",
        ),
        pytest.param(
            [("opt/.wh.t", ""), ("opt/t", None), ("opt/t/new", "n")],
            "/",
            ["opt", "opt/t", "opt/t/new"],
            id="the-whole-image",
        ),
        pytest.param([("opt/.wh.tt", "")], "/opt/t", ["a", "b", "sub", "sub/old"], id="a-sibling"),
    ],
)
def test_a_layer_s_whiteouts_remove_what_the_layers_below_put(
    tmp_path: Path, upper: Layer, path: str, left: list[str]
) -> None:
    """A layer's whiteouts apply to the layers below, wherever they are in its tar: the folder
    asked for, a folder holding it, or something in it. If this fails: an addon's folder holds
    files its image removed, or loses some it has."""
    folder = tmp_path / "out"
    folder.mkdir()
    unpack(archive(tmp_path, BASE, upper), path, folder)
    assert tree(folder) == left


@pytest.mark.rule("runtime.reads-an-image-without-running-it")
@pytest.mark.parametrize(
    "upper",
    [
        pytest.param([("opt/t/../../victim/.wh.f", "")], id="dot-dot"),
        pytest.param([("opt/t/l/.wh.f", "")], id="through-a-link"),
        pytest.param([("opt/t/l/.wh..wh..opq", "")], id="opaque-through-a-link"),
    ],
)
def test_a_whiteout_never_removes_a_file_outside_the_folder(tmp_path: Path, upper: Layer) -> None:
    """The archive is the image's: a crafted whiteout, or one under a link a layer below put,
    must not reach the host's files. If this fails: extracting an addon deletes the user's."""
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "f").write_text("mine")
    folder = tmp_path / "out" / "x"
    folder.mkdir(parents=True)
    unpack(archive(tmp_path, [*BASE, ("opt/t/l", f"->{victim}")], upper), "/opt/t", folder)
    assert (victim / "f").read_text() == "mine"
