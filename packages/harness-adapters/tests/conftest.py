from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_users_packages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The user's system packages (B.7): an empty folder of the test's, not the person's."""
    mine = tmp_path / "system-packages"
    monkeypatch.setenv("HANDLER_SYSTEM_PACKAGES_DIR", str(mine))
    return mine
