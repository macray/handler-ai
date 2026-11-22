"""`given_files.mount_targets`: where each `--mount` is, read from its fields (A.2)."""

from handler_sandbox_kit.given_files import mount_targets


def test_a_mount_s_target_is_its_own_field_whatever_its_source_holds() -> None:
    args = [
        "--mount", "type=bind,source=/home/me/target=x,target=/home/me/a",  # Apple
        "--mount", "type=bind,source=/s,destination=/b,readonly",  # Docker, podman
    ]  # fmt: skip
    assert mount_targets(args) == ["/home/me/a", "/b"]
