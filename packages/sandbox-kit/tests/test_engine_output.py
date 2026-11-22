"""The reason a failed `image` verb gives: its engine's last error line (A.7)."""

import pytest

from handler_sandbox_kit.engine_output import REASON_CHARS, Reason

RULE = "runtime.an-image-verb-says-what-it-did"


@pytest.mark.rule(RULE)
def test_the_reason_is_the_engine_s_last_error_line_without_its_prefix() -> None:
    """Podman's `Error:`, BuildKit's `ERROR:`: the last one wins, its prefix off; other lines
    (progress, a step's own output) are not a reason."""
    reason = Reason()
    for line in [
        "STEP 2/3: RUN false\n",
        "#5 ERROR: process did not complete successfully\n",  # a step's line, not the summary
        "Error: an earlier one\n",
        'ERROR: failed to solve: "/missing": not found\n',
        "some trailing line\n",
    ]:
        reason.feed(line)
    assert reason.said("build failed") == 'build failed: failed to solve: "/missing": not found'


@pytest.mark.rule(RULE)
def test_without_an_error_line_only_what_failed_is_said() -> None:
    reason = Reason()
    reason.feed("Error:   \n")  # nothing after the prefix
    assert (
        reason.said("build failed (podman exit code 125)") == "build failed (podman exit code 125)"
    )
    reason.feed("Error: " + "x" * 1000)
    assert reason.text is not None and len(reason.text) == REASON_CHARS
