"""handler-sandbox-docker's own choices, without an engine: the engine's kind and what each
gives (A.8), the user and its passwd entry (A3), the subordinate ids of `nested` (A.5), the
refusal of a rootless engine, image references, BuildKit's steps (A.7)."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from handler_contracts import RuntimeCheck, SandboxSpec
from handler_sandbox_docker import check, docker, images, launch
from handler_sandbox_kit.launch import UnenforceableError, check_enforceable

ROOTLESS = {"ServerVersion": "29.9.2", "SecurityOptions": ["name=seccomp", "name=rootless"]}
ROOTFUL = {"ServerVersion": "29.9.2", "OperatingSystem": "Arch Linux", "SecurityOptions": []}
DESKTOP = {"ServerVersion": "29.1.0", "OperatingSystem": "Docker Desktop"}


def test_the_engine_s_kind_from_docker_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker.sys, "platform", "linux")
    assert docker.engine_of(ROOTLESS).kind == "rootless"
    assert docker.engine_of(ROOTFUL).kind == "rootful"
    assert docker.engine_of(DESKTOP).kind == "vm"
    monkeypatch.setattr(docker.sys, "platform", "darwin")  # Colima says its VM's distribution
    assert docker.engine_of(ROOTFUL | {"OperatingSystem": "Ubuntu 24.04"}).kind == "vm"


@pytest.mark.rule(
    "confinement.privileged-is-never-root-on-the-computer", "runtime.declares-only-what-it-gives"
)
def test_what_each_kind_gives(monkeypatch: pytest.MonkeyPatch) -> None:
    """A privileged container of a rootful engine is root on the computer: not given there."""
    monkeypatch.setattr(check.display, "found", lambda: True)
    assert "privileged" not in check.abilities("rootful")
    assert {"nested", "privileged"} <= check.abilities("vm")
    assert "display" not in check.abilities("vm")  # a Wayland socket cannot cross a VM


@pytest.mark.rule("runtime.check-starts-nothing-and-says-why")
def test_a_rootless_engine_fails_the_check_but_in_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(check, "buildx", lambda: True)
    monkeypatch.setattr(docker.sys, "platform", "linux")  # a rootful engine is Linux's
    monkeypatch.delenv("HANDLER_SANDBOX_DEV_ROOTLESS_DOCKER", raising=False)
    files = next(i for i in check.items(docker.engine_of(ROOTLESS), ROOTLESS) if i.required)
    assert files.name == "your files" and not files.ok
    monkeypatch.setenv("HANDLER_SANDBOX_DEV_ROOTLESS_DOCKER", "1")
    assert all(i.ok for i in check.items(docker.engine_of(ROOTLESS), ROOTLESS) if i.required)
    rootful = check.items(docker.engine_of(ROOTFUL), ROOTFUL)
    warning = next(i for i in rootful if i.name == "rootless")
    assert not warning.ok and not warning.required and "root on this computer" in warning.detail


@pytest.mark.rule("sandbox.runs-as-the-host-user")
def test_a_rootless_engine_is_refused_at_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launch, "engine", lambda: docker.Engine("rootless", "29"))
    monkeypatch.delenv("HANDLER_SANDBOX_DEV_ROOTLESS_DOCKER", raising=False)
    doc = {
        "apiVersion": "handler.sandbox/v2", "name": "handler-test", "image": "x",
        "argv": ["true"], "env": {}, "workdir": str(tmp_path), "home": "/home/agent",
        "workFolder": {"path": str(tmp_path)}, "network": {"mode": "none"},
    }  # fmt: skip
    spec = SandboxSpec.model_validate(doc)
    with pytest.raises(UnenforceableError, match="rootless Docker"):
        check_enforceable(launch.Docker(), spec)


@pytest.mark.rule("sandbox.runs-as-the-host-user")
def test_the_user_and_its_passwd_entry() -> None:
    """A3 without keep-id: the host user's ids; an entry for them in the image's tables."""
    assert docker.user_args("rootful") == ["--user", f"{os.getuid()}:{os.getgid()}"]
    assert docker.user_args("rootless") == ["--user", "0:0"]  # development only
    table = "root:x:0:0:root:/root:/bin/sh\n"
    added = launch.with_user(table, "agent:x:1000:1000::/home/agent:/bin/sh", 1000)
    assert added.splitlines() == ["root:x:0:0:root:/root:/bin/sh",
                                  "agent:x:1000:1000::/home/agent:/bin/sh"]  # fmt: skip
    present = "root:x:0:0::/root:/bin/sh\nme:x:1000:1000::/home/me:/bin/sh\n"
    assert launch.with_user(present, "agent:x:1000:1000::/h:/bin/sh", 1000) == present


@pytest.mark.rule("confinement.nested-gives-only-the-host-s-part")
def test_nested_subordinate_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rootful: the host user's own range (the container's ids are the host's); a VM: every id
    of the sandbox's but the agent's."""
    monkeypatch.setattr(docker, "host_subids", lambda kind: (100000, 65536))
    uid = os.getuid()
    assert docker.subid_file("uid", "rootful") == f"{uid}:100000:65536\n"
    ranges = [(1, uid - 1), (uid + 1, 65536 - uid - 1)]
    expected = [f"{uid}:{start}:{count}" for start, count in ranges if count > 0]
    assert docker.subid_file("uid", "vm").splitlines() == expected
    # /etc/subgid is keyed by the user too: on the Mac, 501 in group 20
    monkeypatch.setattr(docker, "agent_ids", lambda kind: (501, 20))
    assert docker.subid_file("gid", "vm") == "501:1:19\n501:21:65515\n"
    assert docker.subid_file("gid", "rootful") == "501:100000:65536\n"


@pytest.mark.rule("confinement.nested-gives-only-the-host-s-part")
def test_nested_confinement_lets_an_engine_inside_make_its_namespaces() -> None:
    args = launch.confinement_args(
        SandboxSpec.model_construct(isolation="nested")  # only the level is read
    )
    assert "--security-opt=seccomp=unconfined" in args
    assert "--security-opt=systempaths=unconfined" in args
    assert "--security-opt=no-new-privileges" not in args  # newuidmap's file capabilities


def test_an_image_id_is_a_reference_docker_takes() -> None:
    hex_id = "ab" * 32
    assert docker.reference(hex_id) == f"sha256:{hex_id}"
    assert docker.reference("localhost/handler-ai-toolbox:latest").startswith("localhost/")


@pytest.mark.rule("runtime.an-image-verb-says-what-it-did")
def test_buildkit_steps_are_the_contract_s_step_lines() -> None:
    m = images.STEP.search("#5 [2/4] RUN dnf -y install podman")
    assert m and (m[1], m[2], m[3]) == ("2", "4", "RUN dnf -y install podman")
    assert images.STEP.search("#5 [linux/amd64 1/2] FROM docker.io/library/fedora")
    assert not images.STEP.search("#5 0.21 [ 1/33] Installing podman")  # dnf's own output


@pytest.mark.rule("runtime.an-image-verb-says-what-it-did")
def test_an_image_id_given_to_a_build_is_tagged_for_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BuildKit's FROM takes names only: a harness's TOOLBOX_IMAGE (an id) is named for the
    build, and the name stays (the image's only one before handlerd switches to it)."""
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(images, "docker", lambda *a, **k: calls.append(a) or "")
    built: list[list[str]] = []

    def fake_build(argv: list[str]) -> int:
        built.append(argv)
        Path(argv[0].removeprefix("--iidfile=")).write_text("sha256:" + "cd" * 32)
        return 0

    monkeypatch.setattr(images, "_build", fake_build)
    hex_id = "ab" * 32
    args = [f"TOOLBOX_IMAGE={hex_id}", "OTHER=x"]
    assert images.build(tmp_path, tmp_path / "id", build_args=args, pull=False,
                        no_cache=False, no_intermediate=False) == 0  # fmt: skip
    tag = f"{images.BUILD_BASE}:{hex_id}"
    assert calls == [("tag", f"sha256:{hex_id}", tag)]
    assert f"TOOLBOX_IMAGE={tag}" in built[0] and "OTHER=x" in built[0]
    assert (tmp_path / "id").read_text() == "cd" * 32 + "\n"


def test_a_tmpfs_is_executable() -> None:
    """Docker's tmpfs is noexec unless told; Podman's is not (A3's home)."""
    assert launch._tmpfs("/home/agent", "0700", (1000, 1000)) == [
        "--tmpfs", "/home/agent:exec,mode=0700,uid=1000,gid=1000"
    ]  # fmt: skip


@pytest.mark.rule("runtime.check-starts-nothing-and-says-why")
def test_the_check_only_asks_docker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`check` reads the host: `docker info` and `docker buildx version`, never a command that
    makes anything."""
    ran: list[list[str]] = []

    def run(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        ran.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(ROOTFUL), "")

    def popen(argv: list[str], **_: Any) -> None:
        raise AssertionError(f"started {argv}")

    monkeypatch.setattr(docker.sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", popen)
    check.check()
    assert {argv[1] for argv in ran} == {"buildx", "info"}
    assert RuntimeCheck.model_validate_json(capsys.readouterr().out).runtime.startswith("docker")


@pytest.mark.rule("need.a-file-given-is-that-file")
@pytest.mark.parametrize("kind", ["vm", "rootful"])
def test_a_file_is_linked_in_a_vm_and_mounted_on_linux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Docker Desktop's sharing loses a file the host replaces ("no such file" until the
    container starts again): in a VM, a file is a link in a folder of the instance's; on Linux,
    the file's bind mount holds it, as Podman's.
    If this fails: an editor's save makes an app's file vanish with Docker Desktop."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setattr(launch, "engine", lambda: docker.Engine(kind, "29"))  # ty: ignore[invalid-argument-type]
    mine = tmp_path / "mine"
    mine.mkdir()
    (mine / "agenda.md").write_text("a\n")
    doc = {
        "apiVersion": "handler.sandbox/v2", "name": "handler-test-file", "image": "x",
        "argv": ["true"], "env": {}, "workdir": str(tmp_path), "home": "/home/agent",
        "workFolder": {"path": str(tmp_path)}, "network": {"mode": "none"},
        "folders": [{"source": str(mine / "agenda.md"), "target": str(mine / "agenda.md"),
                     "writable": False}],
    }  # fmt: skip
    instance = launch.Instance(SandboxSpec.model_validate(doc))
    instance.dir.mkdir(parents=True)
    args = launch.Docker().folder(instance.spec.folders[0], instance)
    if kind == "vm":
        linked = instance.dir / "given" / "0"
        assert args == ["--mount", f"type=bind,source={linked},destination={mine},readonly"]
        assert (linked / "agenda.md").stat().st_ino == (mine / "agenda.md").stat().st_ino
    else:
        assert args == [
            "--mount",
            f"type=bind,source={mine / 'agenda.md'},destination={mine / 'agenda.md'},readonly",
        ]
