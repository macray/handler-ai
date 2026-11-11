"""`image read` and `image extract` (A.7) on a fake podman: a copy whose mount the kernel says
is busy (as it does now and then while another build commits) is tried again."""

import os
import sys
from pathlib import Path

import pytest

from handler_sandbox_podman import images

FAKE = """#!{python}
import io, os, sys, tarfile
verb, *args = sys.argv[1:]
if verb == "create":
    print("c0ffee")
elif verb == "cp":
    tries = {state!r}
    seen = int(open(tries).read()) if os.path.exists(tries) else 0
    open(tries, "w").write(str(seen + 1))
    if seen < {busy}:
        sys.exit("Error: mounting storage for container c0ffee: creating overlay mount: "
                 "device or resource busy")
    source, target = args
    if target == "-":
        data = b"Mistral Vibe 3.0.4\\n"
        member = tarfile.TarInfo(os.path.basename(source.split(":", 1)[1]))
        member.size = len(data)
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
            archive.addfile(member, io.BytesIO(data))
    else:
        os.mkdir(target)
"""


def fake_podman(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, busy: int) -> Path:
    """A `podman` whose first `busy` copies fail as a busy mount; the file counting them."""
    state = tmp_path / "copies"
    script = tmp_path / "bin" / "podman"
    script.parent.mkdir()
    script.write_text(FAKE.format(python=sys.executable, state=str(state), busy=busy))
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{script.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(images, "COPY_WAIT", 0)
    return state


@pytest.mark.rule("runtime.reads-an-image-without-running-it")
def test_a_busy_read_is_tried_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    copies = fake_podman(tmp_path, monkeypatch, busy=1)
    assert images.read("localhost/handler-ai-vibe", "/usr/share/handler/version") == 0
    assert capfdbinary.readouterr().out == b"Mistral Vibe 3.0.4\n"
    assert copies.read_text() == "2"


@pytest.mark.rule("runtime.reads-an-image-without-running-it")
def test_a_busy_extract_is_tried_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    copies = fake_podman(tmp_path, monkeypatch, busy=1)
    assert images.extract("localhost/handler-addon", "/addon", tmp_path / "addon") == 0
    assert (tmp_path / "addon").is_dir() and copies.read_text() == "2"


@pytest.mark.rule("runtime.an-image-verb-says-what-it-did")
def test_a_mount_busy_every_time_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    copies = fake_podman(tmp_path, monkeypatch, busy=images.COPY_TRIES)
    assert images.read("localhost/handler-ai-vibe", "/usr/share/handler/version") == 1
    assert "device or resource busy" in capsys.readouterr().err
    assert copies.read_text() == str(images.COPY_TRIES)
