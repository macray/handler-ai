"""An app's page as a phone gets it (remote design): one page, its UI folder's files inlined, and
nothing of the computer beside them."""

from pathlib import Path

import pytest

from handler_control.app_remote import assemble_ui


@pytest.mark.rule("phone-app.its-page-reaches-nothing")
@pytest.mark.parametrize(
    "ref",
    [
        pytest.param("./out.js", id="a-link-out"),
        pytest.param("../secret.js", id="dot-dot"),
        pytest.param("/a/../../secret.js", id="dot-dot-past-a-folder"),
    ],
)
def test_a_page_carries_only_the_files_of_its_ui_folder(tmp_path: Path, ref: str) -> None:
    """A script is inlined only from inside the UI folder: neither a link out of it nor a `..`
    reaches a file beside it.

    If this fails: an app's page, on a phone of the family, carries a file of the computer
    handlerd can read (a key, your notes)."""
    ui = tmp_path / "ui"
    ui.mkdir()
    (tmp_path / "secret.js").write_text("SECRET")
    (ui / "out.js").symlink_to(tmp_path / "secret.js")
    (ui / "app.js").write_text("APP")
    (ui / "index.html").write_text(
        f'<script src="./app.js"></script><script src="{ref}"></script>'
        f'<img src="{ref}"><link rel="stylesheet" href="{ref}">'
    )
    page = assemble_ui(ui)
    assert "<script>APP</script>" in page  # its own file is inlined
    assert "SECRET" not in page
