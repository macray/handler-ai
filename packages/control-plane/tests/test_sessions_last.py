"""Unit tests: a session's line as a device is shown it (D.7, `sessions.one_line`): the agent's
last step or sentence, an ask's title."""

import pytest

from handler_contracts import LAST_MAX
from handler_control.sessions import one_line

FOLDER = "/home/you/code/project"


@pytest.mark.rule("phone.its-list-says-what-each-session-does")
def test_one_line_is_cut_to_its_limit() -> None:
    """Whitespace runs (newlines too) become one space, Markdown's markers before the words go
    and so do its strong emphasis and code spans (their words stay), paths are relative to the session's folder, and a longer line is cut with `…` to the limit.

    If this fails: the phone's card shows the full path of your folder, a Markdown marker or emphasis, or a
    line that runs past what the list may carry."""
    assert one_line("  Run\n  npm\ttest  ", LAST_MAX) == "Run npm test"
    assert one_line(f"Read {FOLDER}/src/notes.md", LAST_MAX, FOLDER) == "Read src/notes.md"
    assert one_line(f"Read {FOLDER}-old/a.md", LAST_MAX, FOLDER) == f"Read {FOLDER}-old/a.md"
    assert one_line("/etc/x", LAST_MAX, "/") == "/etc/x"
    for marked in ("## Result", "> Result", "- Result", "* Result", "1. Result", "> - Result"):
        assert one_line(marked, LAST_MAX) == "Result", marked
    assert one_line("#hashtag stays", LAST_MAX) == "#hashtag stays"
    said = "**pypi.org:443 is blocked.** Run `pip install x`"
    assert one_line(said, LAST_MAX) == "pypi.org:443 is blocked. Run pip install x"
    for kept in ("Allow *.github.com and 2 * 3", "Edit __init__ and __repr__"):
        assert one_line(kept, LAST_MAX) == kept
    assert one_line(" \n- ", LAST_MAX) is None
    long = one_line("é" * 300, LAST_MAX)
    assert long is not None and len(long) == LAST_MAX and long.endswith("…")
    assert one_line("a" * LAST_MAX, LAST_MAX) == "a" * LAST_MAX
