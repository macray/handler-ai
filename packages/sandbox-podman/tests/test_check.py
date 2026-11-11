"""The host check (A.8): Windows' WSL from its kernel's release; what it gives, refused when a
spec needs more."""

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from handler_contracts import Resources, RuntimeCheck, SandboxSpec
from handler_sandbox_kit.launch import UnenforceableError, check_enforceable
from handler_sandbox_podman import check, launch
from handler_sandbox_podman.check import limit_controllers, wsl_version


@pytest.mark.rule("runtime.check-starts-nothing-and-says-why")
def test_wsl_version_from_the_kernel_release() -> None:
    assert wsl_version("6.6.87.2-microsoft-standard-WSL2\n") == 2
    assert wsl_version("5.15.153.1-microsoft-standard-WSL2+") == 2  # a custom WSL 2 kernel
    assert wsl_version("4.4.0-19041-Microsoft") == 1
    assert wsl_version("7.2.11-arch1-1") is None


@pytest.mark.rule("sandbox.refuses-what-it-cannot-enforce")
def test_a_spec_needing_what_the_host_lacks_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A1, one rule: the spec's abilities against what `check` finds here (no /dev/fuse: no
    `nested`)."""
    monkeypatch.setattr(launch, "abilities", lambda: frozenset({"display"}))
    doc = {
        "apiVersion": "handler.sandbox/v2",
        "name": "handler-test",
        "image": "localhost/x:1",
        "argv": ["true"],
        "env": {},
        "workdir": str(tmp_path),
        "home": "/home/agent",
        "workFolder": {"path": str(tmp_path)},
        "network": {"mode": "none"},
    }
    check_enforceable(launch.Podman(), SandboxSpec.model_validate(doc))
    needing = doc | {"isolation": "nested"}
    with pytest.raises(UnenforceableError, match="nested"):
        check_enforceable(launch.Podman(), SandboxSpec.model_validate(needing))


@pytest.mark.rule("runtime.a-limit-is-applied-or-said")
def test_a_limit_the_host_does_not_allow_is_dropped_and_said(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A.8 `limits`: rootless on cgroups v1, or a controller systemd does not delegate."""
    both = Resources(memory="512m", cpus="1.5")
    assert launch.resource_args(both, frozenset({"memory", "cpu"})) == [
        "--memory", "512m", "--cpus", "1.5"
    ]  # fmt: skip
    assert launch.resource_args(both, frozenset({"memory"})) == ["--memory", "512m"]
    assert "--cpus 1.5 not applied" in capsys.readouterr().err
    assert launch.resource_args(Resources(memory="512m"), frozenset()) == []
    assert launch.resource_args(None, frozenset()) == []


@pytest.mark.rule("runtime.a-limit-is-applied-or-said")
def test_limits_are_those_podman_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    def info(version: str, controllers: list[str], rootless: bool = True) -> dict[str, Any]:
        security = {"rootless": rootless}
        return {"host": {"cgroupVersion": version, "cgroupControllers": controllers,
                         "cgroupManager": "systemd", "security": security}}  # fmt: skip

    assert limit_controllers(info("v2", ["cpu", "memory", "pids"])) == {"cpu", "memory"}
    assert limit_controllers(info("v2", ["memory", "pids"])) == {"memory"}  # cpu not delegated
    assert limit_controllers(info("v1", ["cpu", "memory"])) == frozenset()  # only root, on v1
    assert limit_controllers(info("v1", ["cpu", "memory"], rootless=False)) == {"cpu", "memory"}
    assert limit_controllers(None) == frozenset()
    without_systemd = info("v2", ["cpu", "memory"])
    without_systemd["host"]["cgroupManager"] = "cgroupfs"
    monkeypatch.setattr(check, "_own_cgroup_writable", lambda: False)  # e.g. in a container
    assert limit_controllers(without_systemd) == frozenset()
    monkeypatch.setattr(check, "_own_cgroup_writable", lambda: True)
    assert limit_controllers(without_systemd) == {"cpu", "memory"}


@pytest.mark.rule("runtime.check-starts-nothing-and-says-why")
def test_the_check_only_asks_podman(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`check` reads the host: its one command is `podman info`, never one that makes anything."""
    ran: list[list[str]] = []
    info = {"version": {"Version": "6.1.3"}, "host": {"security": {"rootless": True}}}

    def run(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        ran.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(info), "")

    def popen(argv: list[str], **_: Any) -> None:
        raise AssertionError(f"started {argv}")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", popen)
    check.check()
    assert [argv[:2] for argv in ran] == [["podman", "info"]]
    assert RuntimeCheck.model_validate_json(capsys.readouterr().out).runtime == "podman 6.1.3"


@pytest.mark.rule("runtime.check-starts-nothing-and-says-why")
def test_too_few_subordinate_ids_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plain sessions run with fewer than 65535: only agents that run containers and apps need
    them, so the check still passes and says how to add them."""
    monkeypatch.delenv("HANDLER_SANDBOX_DEV_NO_KEEPID", raising=False)
    monkeypatch.setattr(check, "_id_range", lambda kind: 55000)
    host = {"security": {"rootless": True}, "networkBackend": "netavark",
            "pasta": {"executable": "/usr/bin/pasta"}}  # fmt: skip
    found = check.items({"host": host})
    ids = next(i for i in found if i.name == "subordinate ids")
    assert not ids.ok and not ids.required
    assert "agents that run containers and for apps" in ids.detail
    assert "usermod --add-subuids" in ids.detail
    assert all(i.ok for i in found if i.required)


@pytest.mark.rule("confinement.nested-gives-only-the-host-s-part")
@pytest.mark.parametrize("confinement", ["strict", "nested", "privileged"])
def test_a_sandbox_running_containers_gets_its_own_process_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, confinement: str
) -> None:
    """Where podman can set it: podman's default (2048) is too few for engines and containers."""
    host = {"cgroupVersion": "v2", "cgroupManager": "systemd", "security": {"rootless": True}}
    controllers: list[str] = ["memory", "pids"]
    monkeypatch.setattr(
        launch, "podman_info", lambda: {"host": host | {"cgroupControllers": controllers}}
    )
    monkeypatch.setattr(launch, "subid_file", lambda kind: "1000:100000:65536\n")
    spec = SimpleNamespace(isolation=confinement)
    args = launch.Podman().isolation(SimpleNamespace(spec=spec, dir=tmp_path))  # ty: ignore[invalid-argument-type]
    given = args[args.index("--pids-limit") + 1] if "--pids-limit" in args else None
    assert given == (None if confinement == "strict" else str(launch.CONTAINERS_PIDS_LIMIT))
    controllers = ["memory"]  # pids not delegated: podman would refuse the flag
    shutil.rmtree(tmp_path / "nested", ignore_errors=True)
    args = launch.Podman().isolation(SimpleNamespace(spec=spec, dir=tmp_path))  # ty: ignore[invalid-argument-type]
    assert "--pids-limit" not in args
