"""An OCI image archive (what `image save` writes, on Docker and Apple container): its layers'
files, and an image's folder unpacked from them without running the image (A.7 `extract`, `read`):
an engine's own copy out of a container adds what it puts in every container (`/dev`, `/proc`,
Docker's `/.dockerenv`), which a FROM scratch addon image does not hold."""

import gzip
import io
import json
import shutil
import tarfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import IO


class ImageArchiveError(ValueError):
    pass


def _layers(archive: tarfile.TarFile) -> list[IO[bytes]]:
    """The archive's layers, the first one first."""

    def blob(digest: str) -> IO[bytes]:
        try:
            member = archive.extractfile(f"blobs/{digest.replace(':', '/')}")
        except KeyError:
            member = None
        if member is None:
            raise ImageArchiveError(f"image archive: no blob {digest}")
        return member

    index = json.load(archive.extractfile("index.json") or io.BytesIO(b"{}"))
    manifest = json.load(blob(index["manifests"][0]["digest"]))
    if "manifests" in manifest:  # an index of platforms: the first is this machine's
        manifest = json.load(blob(manifest["manifests"][0]["digest"]))
    return [blob(layer["digest"]) for layer in manifest["layers"]]


def layer_files(archive: tarfile.TarFile) -> Iterator[tarfile.TarFile]:
    """Each layer's files, the first layer first. Raises ImageArchiveError."""
    for layer in _layers(archive):
        raw = layer.read()
        data = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
        with tarfile.open(fileobj=io.BytesIO(data)) as files:
            yield files


OPAQUE = ".wh..wh..opq"  # in a layer's folder: that folder replaces the one of the layers below


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _whiteout(name: str, wanted: str, folder: Path) -> None:
    """Apply the whiteout `name` (a path in the image) to `folder`, which holds the image's folder
    `wanted` ("": the whole image) as the layers below left it."""
    marker = PurePosixPath(name)
    parent = "" if str(marker.parent) == "." else str(marker.parent)
    removed = parent if marker.name == OPAQUE else str(marker.parent / marker.name[len(".wh.") :])
    if removed == wanted or not removed or wanted.startswith(f"{removed}/"):
        for child in folder.iterdir():  # `wanted` itself, or a folder holding it, removed
            _remove(child)
    elif not wanted or removed.startswith(f"{wanted}/"):
        inside = folder / removed.removeprefix(f"{wanted}/" if wanted else "")
        if not inside.parent.resolve().is_relative_to(folder.resolve()):
            return  # `..`, or a link a layer below put: never a file outside `folder`
        if marker.name == OPAQUE:
            if inside.is_dir() and not inside.is_symlink():
                for child in inside.iterdir():
                    _remove(child)
        else:
            _remove(inside)


def unpack(saved: Path, path: str, folder: Path) -> None:
    """The folder `path` of the image saved in `saved`, into the existing `folder`, from its
    layers in order: a layer's whiteouts first, which remove what the layers below put (the
    folder itself, or one holding it, too), then its files. Unpacked by the host user, the files
    are theirs. Raises ImageArchiveError."""
    inside_image = str(PurePosixPath(path)).strip("/")
    prefix = f"{inside_image}/" if inside_image else ""  # "": the whole image
    with tarfile.open(saved) as archive:
        for files in layer_files(archive):
            members = files.getmembers()
            for member in members:
                name = member.name.removeprefix("./").rstrip("/")
                if PurePosixPath(name).name.startswith(".wh."):
                    _whiteout(name, inside_image, folder)
            for member in members:
                name = member.name.removeprefix("./")
                if not name.startswith(prefix) or not name:
                    continue
                inside = PurePosixPath(name.removeprefix(prefix))
                if not inside.name.startswith(".wh.") and str(inside) != ".":
                    member.name = str(inside)
                    if member.islnk():  # a hard link names its target from the image's root
                        target = member.linkname.removeprefix("./")
                        member.linkname = target.removeprefix(prefix)
                    files.extract(member, folder, filter="tar")
