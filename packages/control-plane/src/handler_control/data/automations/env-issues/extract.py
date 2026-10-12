"""env-issues: what an agent lacked in its environment, from the conversation of a stopped session.

Reads $HANDLER_INPUT/transcript.md, asks the first model of `services.llm` about it in parts (a long
conversation is cut at its events), and writes one line per finding to $HANDLER_OUTPUT/note.md:

    - <date> · <project>/<agent> · <kind> · <what> · session <id>

Nothing is written when there is no finding (then nothing is appended).
"""

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

CHUNK = 60_000  # characters of transcript per model call
INPUT, OUTPUT = Path(os.environ["HANDLER_INPUT"]), Path(os.environ["HANDLER_OUTPUT"])


def chunks(text: str) -> list[str]:
    """The transcript in parts of at most CHUNK characters, cut before an event (`[seq]`)."""
    parts, current = [], ""
    for piece in re.split(r"(?m)^(?=#* ?\[\d+\])", text):
        if current and len(current) + len(piece) > CHUNK:
            parts.append(current)
            current = ""
        current += piece[:CHUNK]
    return parts + ([current] if current.strip() else [])


def ask(model: str, part: str) -> list[dict]:
    answer = subprocess.run(
        [
            "handler-llm",
            "--model",
            model,
            "--prompt",
            "prompt.md",
            "--schema",
            "findings.schema.json",
        ],
        input=part,
        capture_output=True,
        text=True,
        check=False,
    )
    if answer.returncode != 0:
        sys.exit(f"handler-llm failed: {answer.stderr.strip()}")
    return json.loads(answer.stdout)["findings"]


def main() -> None:
    model = tomllib.loads(Path("automation.toml").read_text())["services"]["llm"][0]
    event = json.loads((INPUT / "event.json").read_text())
    text = (INPUT / "transcript.md").read_text()
    where = f"{event.get('project') or 'outside projects'}/{event.get('agent') or event['agentId']}"
    date = event["t"][:10]
    lines, parts = [], chunks(text)
    for part in parts:
        for finding in ask(model, part):
            what = " ".join(finding["what"].split())
            kind, session = finding["kind"], event["sessionId"]
            lines.append(f"- {date} · {where} · {kind} · {what} · session {session}")
    if lines:
        (OUTPUT / "note.md").write_text("\n".join(lines) + "\n")
    print(f"{len(lines)} finding(s) in {len(parts)} part(s)")


if __name__ == "__main__":
    main()
