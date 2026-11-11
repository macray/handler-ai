"""The subordinate ids of `nested` (A.5): what inner rootless podman maps."""

import pytest

from handler_sandbox_podman import podman


@pytest.mark.rule("confinement.nested-gives-only-the-host-s-part")
def test_both_files_are_keyed_by_the_agent_s_uid(monkeypatch: pytest.MonkeyPatch) -> None:
    """/etc/subgid is keyed by the user too: one whose gid is not its uid (a Mac's 501 in group
    20, `users` on openSUSE) gets its ranges there, every gid but its own."""
    monkeypatch.setattr(podman, "agent_ids", lambda: (501, 20))
    monkeypatch.setattr(podman, "_userns_size", lambda kind: 65536)
    assert podman.subid_file("uid") == "501:1:500\n501:502:65034\n"
    assert podman.subid_file("gid") == "501:1:19\n501:21:65515\n"
