"""D.4: automatic image updates, as handlerd shows them. A run is not started here: it would rebuild
the machine's real harness images (the test daemon has them); runs are tested with a fake build
store (packages/control-plane/tests/test_image_updates.py)."""

import pytest

from ..support.daemon import Daemon


@pytest.mark.rule("image.updated-on-a-schedule")
def test_updates_are_weekly_by_default_and_can_be_changed(daemon: Daemon) -> None:
    with daemon.http() as c:
        view = c.get("/v1/image-updates").json()
        assert view["schedule"] == "weekly" and view["nextRun"] and not view["running"]
        assert c.put("/v1/image-updates", json={"schedule": "off"}).json()["schedule"] == "off"
        assert "nextRun" not in c.get("/v1/image-updates").json()
        assert c.put("/v1/image-updates", json={"schedule": "hourly"}).status_code == 422
        c.put("/v1/image-updates", json={"schedule": "weekly"})
