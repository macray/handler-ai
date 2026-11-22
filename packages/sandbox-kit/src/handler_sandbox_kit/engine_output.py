"""What an engine's output says went wrong: the reason a failed `image` verb gives on its last
line (A.7, rule `runtime.an-image-verb-says-what-it-did`), the engine's own words."""

import re

# Podman's "Error: …", BuildKit's "ERROR: …" (Docker, Apple container), Apple's CLI "Error: …"
_ERROR = re.compile(r"^\s*(?:Error|ERROR|error):\s*")
REASON_CHARS = 300  # one line: a reason, not a log


class Reason:
    """The last error line an engine wrote, fed its output line by line."""

    def __init__(self) -> None:
        self.text: str | None = None

    def feed(self, line: str) -> None:
        if (m := _ERROR.match(line)) and (text := self.reason_in(line[m.end() :].strip())):
            self.text = text[:REASON_CHARS]

    def reason_in(self, error: str) -> str:
        """The reason in an error line, the line itself here; an engine whose errors nest their
        causes takes its innermost out."""
        return error

    def said(self, failed: str) -> str:
        """`failed`, with the engine's reason when it gave one."""
        return f"{failed}: {self.text}" if self.text else failed
