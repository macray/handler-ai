"""The notes history in the web UI (D.5), in a real browser against a real handlerd: a folder an
agent may write shows its changes, one opened shows its lines, Undo puts its files back; a
folder no agent writes shows no history."""

import re
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from handler_control.settings import WEB_UI

from ..control.test_notes_history import until_committed
from ..support import dev_env
from ..support.daemon import Daemon, start_daemon
from .browser import PW_IMAGE, image_present

pytestmark = [
    pytest.mark.skipif(not (WEB_UI / "index.html").is_file(), reason="web UI not built"),
    pytest.mark.skipif(not image_present(), reason=f"{PW_IMAGE} not pulled"),
    pytest.mark.timeout(dev_env.IMAGE_TIMEOUT),
]


@pytest.fixture(scope="module")
def root() -> Iterator[Path]:
    base = dev_env.scope_root() / f"notes-ui-{uuid.uuid4().hex[:8]}"
    (base / "me").mkdir(parents=True)
    (base / "me" / "likes.md").write_text("# Likes\n\n- tea\n")
    (base / "read-only").mkdir()
    yield base
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture(scope="module")
def daemon(root: Path) -> Iterator[Daemon]:
    yield from start_daemon(extra_env={"HANDLER_NOTES_DIR": str(root)})


@pytest.fixture
def page(browser: Browser, daemon: Daemon) -> Iterator[Page]:
    context = browser.new_context()
    page = context.new_page()
    page.goto(daemon.ui_url())
    yield page
    context.close()


@pytest.mark.rule("notes.writable-has-a-history", "notes.handler-writes-only-what-you-asked")
def test_a_change_is_seen_and_undone(page: Page, daemon: Daemon, root: Path) -> None:
    """If this fails: the history is kept but you cannot see nor undo what an agent changed."""
    daemon.create_ad_hoc(
        "fake", daemon.make_scope(), knowledge=[{"folder": "me", "access": "write"}]
    )
    (root / "me" / "likes.md").write_text("# Likes\n\n- tea\n- long walks\n")
    daemon.restart()  # what changed while it was off: committed at its start, beside serving
    with daemon.http() as c:
        until_committed(c, "me", 2)
    page.goto(daemon.ui_url())
    page.goto(f"{daemon.base_url}/#/notes?path=read-only")
    expect(page.get_by_text("This folder is empty.")).to_be_visible()
    expect(page.get_by_test_id("notes-history")).to_have_count(0)

    page.goto(f"{daemon.base_url}/#/notes?path=me")
    changes = page.get_by_test_id("notes-change")
    expect(changes).to_have_count(2)
    # closed, it says its files and what changed in them; nothing to undo before it is opened
    expect(changes.first).to_contain_text("Changed while Handler was not running")
    expect(changes.first.get_by_test_id("notes-change-said")).to_have_text(
        re.compile(r"likes\.md\s*added 1 line under Likes")
    )
    expect(changes.first.get_by_test_id("notes-undo")).to_have_count(0)
    changes.first.get_by_test_id("notes-change-toggle").click()
    expect(page.get_by_test_id("notes-change-files")).to_contain_text("+- long walks")
    expect(page.get_by_test_id("notes-change-files")).to_contain_text("added 1 line under Likes")
    changes.first.get_by_test_id("notes-undo").click()
    expect(page.get_by_test_id("notes-undo-dialog")).to_contain_text("likes.md put back")
    page.get_by_test_id("notes-undo-confirm").click()
    expect(page.get_by_test_id("notes-history-told")).to_contain_text("Put back as before.")
    expect(changes).to_have_count(3)
    expect(changes.first).to_contain_text("Undo (by you)")
    expect(changes.first).to_have_text(re.compile(r"likes\.md\s*put back"))
    assert (root / "me" / "likes.md").read_text() == "# Likes\n\n- tea\n"
