"""The `image` verbs (contract A.7) on Apple container, and the network filter's image with the
relay exported next to it (`build-proxy`).

`container build` has no `--iidfile`: a build is tagged `localhost/handler-ai-build:<id>`,
its id read from `image inspect`, and the tag kept: `container` refers to an image by a name only,
and deletes one left without a name at once (1.7.1). Images only such a tag names are pruned at
a later build (`prune_builds`), aged by the time written in their tag.
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path, PurePosixPath

from handler_contracts import ImageInfo, ProxyImage
from handler_sandbox_kit import egress, image_archive, relay
from handler_sandbox_kit.engine_output import Reason

from .container import (
    FILTER_IMAGE,
    ContainerError,
    container,
    find,
    image_id,
    image_info,
    names,
    quiet,
    reference,
    running_from,
    variant,
)
from .launch import PROG, relay_dir

READ_LIMIT = 1 << 20  # A.7: `read` gives a file of at most 1 MiB
# BuildKit's step line, "#5 [linux/arm64 2/4] RUN …" (a stage or platform first, or none), not a
# RUN's own output ("#5 0.21 [ 1/33] …": dnf's)
STEP = re.compile(r"^#\d+ \[\s*(?:\S+\s+)?(\d+)/(\d+)\]\s*(.*)")
# Apple's errors nest their causes ("internalError: … (cause: … NSLocalizedFailureReason=Rosetta
# is not installed}…"): the innermost reason the Virtualization framework gave is the one to say
_FAILURE_REASON = re.compile(r"NSLocalizedFailureReason=([^}\"]+?)\.?[}\"]")


class AppleReason(Reason):
    """An engine's reason, Apple's innermost failure reason when its error carries one."""

    def reason_in(self, error: str) -> str:
        return m[1].strip() if (m := _FAILURE_REASON.search(error)) else error


def _fail(message: str) -> int:
    print(f"{PROG}: {message}", file=sys.stderr)
    return 1


def _build(argv: list[str]) -> tuple[int, Reason]:
    """Run `container build`, its output turned into the contract's `STEP n/m: …` lines (A.7); its
    exit code, and the reason it gave when it failed."""
    proc = subprocess.Popen(
        ["container", "build", "--progress", "plain", *argv],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )  # fmt: skip
    assert proc.stdout is not None
    seen: set[tuple[str, str]] = set()
    reason = AppleReason()
    for line in proc.stdout:
        reason.feed(line)
        if (m := STEP.search(line)) and (m[1], m[2]) not in seen:
            seen.add((m[1], m[2]))
            print(f"STEP {m[1]}/{m[2]}: {m[3].strip()}", flush=True)
        else:
            print(line, end="", flush=True)
    return proc.wait(), reason


def build(
    context: Path,
    id_file: Path,
    *,
    build_args: list[str],
    pull: bool,
    no_cache: bool,
    no_intermediate: bool,  # BuildKit keeps no intermediate images anyway
) -> int:
    tag = build_tag(datetime.now(UTC))
    argv = ["--tag", tag, "--file", str(context / "Containerfile")]
    argv += [a for arg in build_args for a in ("--build-arg", arg)]
    argv += ["--pull"] if pull else []
    argv += ["--no-cache"] if no_cache else []
    code, reason = _build([*argv, str(context)])
    if code:
        return _fail(reason.said("build failed"))
    info = image_info(tag)
    if info is None:
        return _fail(f"built, but {tag} is not found")
    id_file.write_text(image_id(info) + "\n")
    prune_builds(keep=image_id(info))
    return 0


BUILD_REPO = "localhost/handler-ai-build"
STALE = timedelta(days=1)  # far more than a build and its check: another builder's is never one
# A build's age is the time in its tag, never its image's creation date: an image whose steps are
# all cached, or only add labels, has its base image's, years old, and a build running beside it
# would prune it before its builder tags it with its name.
_TAGGED = "%Y%m%dT%H%M%SZ"


def build_tag(now: datetime) -> str:
    return f"{BUILD_REPO}:{now.strftime(_TAGGED)}-{uuid.uuid4().hex[:8]}"


def _tagged_at(name: str) -> datetime | None:
    """When a build tag was made; None for a name that is not one."""
    repo, _, tag = name.partition(":")
    if repo != BUILD_REPO:
        return None
    try:
        return datetime.strptime(tag.split("-")[0], _TAGGED).replace(tzinfo=UTC)
    except ValueError:
        return None


def prune_builds(keep: str, now: datetime | None = None) -> None:
    """The images only build tags name (an image without a name is gone, so a build is
    tagged until it is switched): a replaced one kept while a sandbox ran from it, a build whose
    builder was killed. Removed once their newest tag is a day old and unused, except `keep` (a
    cached build gives an older image back)."""
    try:
        listed = json.loads(container("image", "list", "--format", "json", check=False) or "[]")
    except ValueError:
        return
    named: dict[str, list[str]] = {}
    for entry in listed:
        config = entry.get("configuration") if isinstance(entry, dict) else None
        if not isinstance(config, dict) or not isinstance(entry.get("id"), str):
            continue
        named.setdefault(entry["id"], []).append(str(config.get("name")))
    old = (now or datetime.now(UTC)) - STALE
    for image, all_names in named.items():
        tagged = [_tagged_at(n) for n in all_names]
        if image == keep or None in tagged or max(t for t in tagged if t) > old:
            continue
        if not running_from(image):
            quiet("image", "delete", *all_names)


def _created(info: dict) -> datetime:
    for found in find(variant(info), "created"):  # the variant's config's
        if isinstance(found, str):
            return datetime.fromisoformat(found.replace("Z", "+00:00"))
    raise ContainerError("image inspect: no creation time")


def info_of(ref: str) -> ImageInfo | None:
    info = image_info(ref)
    if info is None:
        return None
    return ImageInfo(id=image_id(info), created=_created(info))


def inspect(ref: str) -> int:
    found = info_of(ref)
    if found is None:
        return _fail(f"no image {ref}")
    print(found.model_dump_json(by_alias=True))
    return 0


def read(ref: str, path: str) -> int:
    """A file of the image, read from its layers without running it (an addon image has no
    shell); the topmost layer that has it wins."""
    wanted = str(PurePosixPath(path)).lstrip("/")
    with tempfile.TemporaryDirectory() as tmp:
        saved = Path(tmp) / "image.tar"
        try:
            container("image", "save", reference(ref), "--output", str(saved), timeout=600)
        except ContainerError as e:
            return _fail(str(e))
        content: bytes | None = None
        with tarfile.open(saved) as archive:
            for files in image_archive.layer_files(archive):
                for member in files:
                    if member.name.lstrip("./") != wanted:
                        continue
                    if not member.isfile():
                        return _fail(f"{path} is not a file")
                    if member.size > READ_LIMIT:
                        return _fail(f"{path} is larger than 1 MiB")
                    extracted = files.extractfile(member)
                    content = extracted.read() if extracted else None
    if content is None:
        return _fail(f"no file {path} in {ref}")
    sys.stdout.buffer.write(content)
    return 0


def extract(ref: str, path: str, folder: Path) -> int:
    """The folder `path` of the image copied to `folder` (made here: it must not exist), from its
    layers in order without running it (the kit's image_archive)."""
    if folder.exists() or not folder.parent.is_dir():
        return _fail(f"{folder} exists, or its parent folder does not")
    with tempfile.TemporaryDirectory() as tmp:
        saved = Path(tmp) / "image.tar"
        try:
            container("image", "save", reference(ref), "--output", str(saved), timeout=1800)
        except ContainerError as e:
            return _fail(str(e))
        folder.mkdir()
        try:
            image_archive.unpack(saved, path, folder)
        except image_archive.ImageArchiveError as e:
            shutil.rmtree(folder, ignore_errors=True)
            return _fail(str(e))
    if not any(folder.iterdir()):
        folder.rmdir()
        return _fail(f"no folder {path} in {ref}")
    return 0


def tag(source: str, target: str) -> int:
    try:
        container("image", "tag", reference(source), target)
    except ContainerError as e:
        return _fail(str(e))
    return 0


def remove(image_id: str) -> int:
    """Refused while a container runs from it: `container` itself deletes the names of an image
    in use (the image stays, nameless, and cannot be removed any more)."""
    found = names(image_id)
    if not found:
        return _fail(f"{image_id[:12]} missing")
    if running_from(image_id):
        return _fail(f"{image_id[:12]} in use by a running container")
    try:
        container("image", "delete", *found)  # every name: the image goes with its last one
    except ContainerError as e:
        return _fail(f"{image_id[:12]} in use: {e}")
    return 0


def pull(ref: str) -> int:
    try:
        container("image", "pull", ref, timeout=1800)
    except ContainerError as e:
        return _fail(str(e))
    return 0


RELAY_SOURCE = "handler-relay.source"  # beside it: the digest of the source it was built from
# what its build exports: the relay, and the caches' overlay program it starts (launch.OVERLAY)
RELAY_FILES = ("handler-relay", "fuse-overlayfs")


def relay_source_digest() -> str:
    with resources.as_file(relay.source_dir()) as source:
        files = sorted(
            p
            for p in source.iterdir()
            if p.suffix == ".go" or p.name in ("go.mod", "Containerfile")
        )
        return hashlib.sha256(b"".join(p.read_bytes() for p in files)).hexdigest()


def relay_current() -> bool:
    """handler-relay exported, from the source this Handler has (an older one may lack a flag
    the launcher gives it)."""
    built = relay_dir() / RELAY_SOURCE
    return all((relay_dir() / name).exists() for name in RELAY_FILES) and (
        built.exists() and built.read_text().strip() == relay_source_digest()
    )


def proxy() -> int:
    """Built when both are: the filter's image (per account, Apple's store) and handler-relay
    (per HOME), current: then the image's id; else none, and handlerd builds both (D.4)."""
    image = info_of(FILTER_IMAGE) if relay_current() else None
    print(ProxyImage(ref=FILTER_IMAGE, image=image).model_dump_json(by_alias=True))
    return 0


def build_relay() -> int:
    """handler-relay built for the VMs' Linux, exported to relay_dir(), which sandboxes mount,
    with the digest of its source beside it (relay_current)."""
    with (
        resources.as_file(relay.source_dir()) as relay_source,
        tempfile.TemporaryDirectory() as tmp,
    ):
        out = ["--no-cache", "--output", f"type=local,dest={tmp}"]
        source = ["--file", str(relay_source / "Containerfile"), str(relay_source)]
        code, reason = _build([*out, *source])
        if code:
            return _fail(reason.said("handler-relay's build failed"))
        relay_dir().mkdir(parents=True, exist_ok=True)
        for name in RELAY_FILES:
            # container 1.6.1 writes it at <dest>/out.tar/linux_arm64/: a folder per platform
            built = next(Path(tmp).rglob(name), None)
            if built is None:
                return _fail(f"handler-relay's build gave no /{name}")
            shutil.copyfile(built, relay_dir() / f"{name}.new")
            (relay_dir() / f"{name}.new").chmod(0o755)
            (relay_dir() / f"{name}.new").replace(relay_dir() / name)
        (relay_dir() / RELAY_SOURCE).write_text(relay_source_digest() + "\n")
    return 0


def build_proxy() -> int:
    """The network filter's image (base pulled again, no cache: its security updates), and
    handler-relay (build_relay)."""
    with resources.as_file(egress.proxy_dir()) as proxy_dir:
        argv = ["--tag", FILTER_IMAGE, "--pull", "--no-cache"]
        code, reason = _build([*argv, "--file", str(proxy_dir / "Containerfile"), str(proxy_dir)])
        if code:
            return _fail(reason.said("the network filter's build failed"))
    if (code := build_relay()) != 0:
        return code
    check = subprocess.run(
        ["container", "run", "--rm", FILTER_IMAGE, "--version"],
        capture_output=True, text=True, timeout=300, check=False,
    )  # fmt: skip
    if check.returncode != 0:
        return _fail(f"the network filter does not start: {check.stderr.strip()[-300:]}")
    return 0
