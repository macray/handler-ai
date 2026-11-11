"""A file a sandbox writes is alone in a folder of its own (contract A.1), so a runtime that mounts
folders only (Apple container) can mount it:

    <data>/agent-state/<agent>/<runs>/<slot>   a file → <slot>/<slot>
    <data>/accounts/<name>/credential          → <name>/login/credential

A file right in <agent>/ is left as it was: a slot from before 2026-10-02, when an agent's state
had no <runs> folder, that nothing reads.
"""

from ..settings import Settings


def migrate(settings: Settings) -> None:
    for runs in settings.data_dir.glob("agent-state/*/*/"):
        for slot in [p for p in runs.iterdir() if p.is_file()]:
            moved = slot.with_name(slot.name + ".moving")
            slot.rename(moved)
            slot.mkdir(mode=0o700)
            moved.rename(slot / slot.name)
    for credential in settings.data_dir.glob("accounts/*/credential"):
        if credential.is_file():
            (credential.parent / "login").mkdir(mode=0o700, exist_ok=True)
            credential.rename(credential.parent / "login" / "credential")
