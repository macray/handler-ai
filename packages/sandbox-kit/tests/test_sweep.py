"""`sweep` and the kit's instance folders: removed when the launcher that made them is dead, kept
while it runs, even before it has written who it is.

Spec: contract A "Sandbox" (the `sweep` verb: never what a live launcher made).
Whether a launcher runs: test_launcher.py."""

from pathlib import Path

import pytest

from handler_sandbox_kit import launch
from handler_sandbox_kit.launcher import launcher_label


@pytest.mark.rule("sandbox.sweep-spares-live-launchers")
@pytest.mark.parametrize(
    ("launcher_file", "kept"),
    [
        pytest.param(launcher_label(), True, id="live-launcher"),
        pytest.param("1:0", False, id="dead-launcher"),  # pid 1 did not start at tick 0
        pytest.param(None, True, id="launcher-file-not-written-yet"),
    ],
)
def test_sweep_removes_only_the_folders_of_dead_launchers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launcher_file: str | None, kept: bool
) -> None:
    """A folder without its launcher's file is just made: its launcher writes the file right
    after. If this fails: sweep (run when handlerd starts) deletes a starting or running
    sandbox's folder, or leaves dead ones piling up."""
    monkeypatch.setattr(launch, "_instances_dir", lambda: tmp_path)
    folder = tmp_path / "instance"
    folder.mkdir()
    if launcher_file is not None:
        (folder / launch._LAUNCHER_FILE).write_text(launcher_file)
    launch._sweep_instances()
    assert folder.exists() is kept


def test_sweep_without_any_instance_folder_does_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host that never ran a sandbox has no instances folder.
    If this fails: handlerd's first start errors in its sweep."""
    monkeypatch.setattr(launch, "_instances_dir", lambda: tmp_path / "sandboxes")
    launch._sweep_instances()


@pytest.mark.rule("sandbox.leaves-nothing-behind")
@pytest.mark.parametrize("mode", [0o500, 0o300, 0o000], ids=["r-x", "-wx", "---"])
def test_a_folder_the_agent_made_read_only_is_removed_with_its_sandbox(
    tmp_path: Path, mode: int
) -> None:
    """Vibe leaves `dr-x------` folders in its home (its logs).
    If this fails: each such sandbox's folder stays for good, its launcher's file gone first,
    so that the sweep never retries it."""
    folder = tmp_path / "instance"
    locked = folder / "home" / ".vibe" / "logs"
    (locked / "deeper").mkdir(parents=True)
    (locked / "deeper" / "log.txt").write_text("x")
    (locked / "session.json").write_text("{}")
    (folder / launch._LAUNCHER_FILE).write_text("1:0")
    (locked / "deeper").chmod(mode)
    locked.chmod(mode)
    try:
        assert launch._remove_instance_dir(folder) is None
        assert not folder.exists()
    finally:
        if locked.exists():
            locked.chmod(0o700)
            (locked / "deeper").chmod(0o700)


def test_a_folder_not_removed_keeps_its_launcher_s_file_for_the_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If this fails: a sandbox folder its cleanup could not remove is never swept again."""

    def refuse(*_a: object, **_k: object) -> None:
        raise OSError("busy")

    folder = tmp_path / "instance"
    (folder / "home").mkdir(parents=True)
    (folder / launch._LAUNCHER_FILE).write_text("1:0")
    monkeypatch.setattr(launch.shutil, "rmtree", refuse)
    assert "busy" in (launch._remove_instance_dir(folder) or "")
    assert (folder / launch._LAUNCHER_FILE).exists()
