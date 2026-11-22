"""`handler ask --listen`: ask by voice (D.24, D.25). What you say is written down by your speech
model (Settings → Expert → Voice), then asked as `handler ask` would.

    handler ask --listen            records until Enter, then as `handler ask` with what it heard
    handler ask --listen --toggle   for a key (a Stream Deck): a first press records, the next
                                    stops it ("got it" at once); how it went is a sound and a
                                    notification naming what was heard; a question back: the
                                    next press answers it, within 2 minutes
    handler ask --listen --check    what this computer will use, and what is missing; run by a
                                    key (no terminal), also a sound and a notification

The toggle: the process of the first press, the listener, holds a lock on `listener` in
`voice_device.workdir()`, which holds its pid; a press finding it held tells the listener
(SIGUSR1) and ends at once. The listener lives while it records, while it waits for Handler, and
up to QUESTION_WAIT after a question back: the exchange is in its memory only, never on disk.

Never silent: whatever ends a press's listener is a sound and a notification; what went wrong
before Handler answered (no recorder, Handler not answering, the listener failing) is also a line
of `log_path()`, never with what you said. What reached Handler is in its Ask history.

Light on purpose (`entry.py` comes here before loading the rest of the CLI): the recording starts
first; the client is loaded while you speak.
"""

import base64
import contextlib
import fcntl
import os
import select
import signal
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from . import voice_device as vd

LOG_LINES = 200  # the log keeps its last lines only
QUESTION_WAIT = 120.0  # a question back is answered by a press within this, else dropped
MIN_SECONDS = 0.3  # shorter: nothing was said
INSTALL = {
    "recorder": "PipeWire (pw-record), PulseAudio (parecord) or ALSA (arecord)",
    "player": "PipeWire (pw-play), PulseAudio (paplay) or ALSA (aplay)",
    "notifier": "libnotify (notify-send)",
}


def run(*, toggle: bool, check: bool) -> int:
    if check:
        return checked()
    return pressed() if toggle else in_terminal()


# ── a key: press to start, press to stop ─────────────────────────────────────────────────────


def pressed() -> int:
    """One press: the listener's next step when one runs, else this process becomes it."""
    dev = vd.device()
    fd = os.open(vd.workdir() / "listener", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:  # a listener runs: tell it
            pid = os.pread(fd, 32, 0).decode().strip()
            if pid.isdigit():
                os.kill(int(pid), signal.SIGUSR1)
            return 0
        listener = Listener(dev)  # its signal handler set before its pid is seen
        os.ftruncate(fd, 0)
        os.pwrite(fd, str(os.getpid()).encode(), 0)
        try:
            return listener.run()
        finally:
            os.ftruncate(fd, 0)
    finally:
        os.close(fd)  # the lock goes with it


class Listener:
    """The first press's process: records, asks, says how it went; a question back, it waits
    for the next press to record your answer."""

    def __init__(self, dev: vd.Device) -> None:
        self.dev = dev
        self.press = threading.Event()
        self.client: Any = None  # the client module, loaded while the first recording runs
        signal.signal(signal.SIGUSR1, lambda *_: self.press.set())

    def hear(self) -> bytes:
        """Record until the next press, at most MAX_SECONDS; "got it" once stopped."""
        self.press.clear()
        try:
            recording = vd.record(self.dev)
        except OSError as e:
            raise NoRecorderError from e
        vd.play(self.dev, "start")
        from . import client  # noqa: PLC0415 — loaded while you speak, not before

        self.client = client
        self.press.wait(vd.MAX_SECONDS)
        audio = recording.stop()
        vd.play(self.dev, "heard")
        return audio

    def run(self) -> int:
        try:
            audio = self.hear()
            return self.exchange(self.client.Daemon(), audio)
        except Exception as e:  # never silent: whatever ends it is heard and said
            return self.failed(e)

    def failed(self, e: Exception) -> int:
        """How the listener ended on an error, in the person's words; what Handler did not see
        is also written to the log."""
        from . import client  # noqa: PLC0415 — loaded already, unless recording failed

        if isinstance(e, client.ClientError):  # Handler answered: its Ask history has it
            return self.tell("failed", "Ask could not answer", said(e))
        if isinstance(e, NoRecorderError):
            title, body = "No recorder", "handler ask --listen --check says what to install."
        elif isinstance(e, client.httpx.HTTPError):  # handlerd too slow, gone, or not started
            title, body = "Handler did not answer", "Is Handler running? Try again, or open it."
        else:
            title, body = "The listener failed", f"What went wrong is in {log_path()}."
        logged(f"{title}: {body}", e)
        return self.tell("failed", title, body)

    def exchange(self, daemon: Any, audio: bytes) -> int:
        """Ask what was heard; a question back is answered by the next press's recording."""
        turns: list[dict[str, str]] = []
        while True:
            text = written_down(daemon, audio, "key")
            if not text:
                return self.tell("failed", "Nothing heard", "Press, speak, press again.")
            turns.append({"who": "you", "text": text})
            answer = asked(daemon, turns)
            if answer["kind"] == "pick":
                return self.picked(answer, text)
            if answer["kind"] == "none":
                return self.tell("failed", "No app does that", f"“{text}”: {answer['summary']}")
            question = answer["question"]
            self.tell("question", "Handler asks", f"{question}\nPress to answer.")
            self.press.clear()
            if not self.press.wait(QUESTION_WAIT):
                return 1
            turns.append({"who": "handler", "text": question})
            audio = self.hear()

    def picked(self, answer: dict[str, Any], text: str) -> int:
        """What the app answered: done, done with something to read, failed; a job's: started.
        Its notification says what was heard, so a wrong word is seen at once."""
        title = f"{answer['app']} · {answer['action']}"
        heard = f"\nHeard: “{text}”"
        run = answer["run"]
        if run["state"] == "running":
            return self.tell(
                "done", title, f"Its job is on it: its answer comes to your inbox.{heard}"
            )
        if run["state"] == "failed":
            return self.tell("failed", title, (run.get("error") or "It failed.") + heard)
        result = run["result"]
        kind = {"ok": "done", "attention": "attention"}.get(result["status"], "failed")
        return self.tell(kind, title, result["summary"] + heard)

    def tell(self, kind: str, title: str, body: str) -> int:
        """A sound and a notification; 0 for done (with something to read or not) and a question."""
        heard(self.dev, kind, title, body)
        return 1 if kind == "failed" else 0


def heard(dev: vd.Device, kind: str, title: str, body: str) -> None:
    """Play `kind`'s sound and notify; one failing does not stop the other."""
    with contextlib.suppress(OSError):
        vd.play(dev, kind)
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        vd.notify(dev, title, body)


class NoRecorderError(Exception):
    """This computer has no recorder, or its recorder fails to start."""


def log_path() -> Path:
    """Where the listener writes what went wrong before Handler answered: the user's state
    folder, as handlerd's (`~/.local/state/handler-ai/`)."""
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "handler-ai" / "listen.log"


def logged(line: str, e: BaseException) -> None:
    """A failure, as one dated line and its traceback, kept to the last LOG_LINES lines. Only
    what went wrong: never what was said (the words are in neither the line nor the frames)."""
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        trace = "".join(traceback.format_exception(type(e), e, e.__traceback__, chain=False))
        old = path.read_text().splitlines() if path.exists() else []
        new = [*old, f"{stamp}  {line}", *("    " + t for t in trace.splitlines())]
        path.write_text("\n".join(new[-LOG_LINES:]) + "\n")
        path.chmod(0o600)
    except OSError:  # a log that cannot be written: the sound and notification still say it
        pass


# ── in a terminal: Enter stops ───────────────────────────────────────────────────────────────


def in_terminal() -> int:
    dev = vd.device()
    try:
        recording = vd.record(dev)
    except OSError:
        print("no recorder: handler ask --listen --check says what to install", file=sys.stderr)
        return 1
    vd.play(dev, "start")
    print(f"Listening… Enter to stop (at most {vd.MAX_SECONDS} s).", flush=True)
    from .ask_commands import answered  # noqa: PLC0415 — while you speak
    from .client import ClientError, Daemon  # noqa: PLC0415

    if sys.stdin.isatty():
        ready, _, _ = select.select([sys.stdin], [], [], vd.MAX_SECONDS)
        if ready:
            sys.stdin.readline()
    else:  # no terminal to press Enter in: MAX_SECONDS
        threading.Event().wait(vd.MAX_SECONDS)
    audio = recording.stop()
    try:
        daemon = Daemon()
        text = written_down(daemon, audio, "cli")
        if not text:
            print("nothing heard")
            return 1
        print(f"you said: {text}")
        return answered(daemon, [{"who": "you", "text": text}], spoken=True)
    except ClientError as e:
        print(said(e), file=sys.stderr)
        return 1


# ── what both do ─────────────────────────────────────────────────────────────────────────────


def written_down(daemon: Any, audio: bytes, via: str) -> str:
    """What was said, written down by the speech model (D.25); "" when nothing was."""
    if vd.seconds(audio) < MIN_SECONDS:
        return ""
    body = {"audio": base64.b64encode(audio).decode(), "format": "wav", "via": via}
    return daemon.call("POST", "/v1/voice/transcribe", body, timeout=120)["text"].strip()


def asked(daemon: Any, turns: list[dict[str, str]]) -> dict[str, Any]:
    from .ask_commands import local_zone  # noqa: PLC0415

    body = {"turns": turns, "timezone": local_zone(), "via": "key", "spoken": True}
    return daemon.call("POST", "/v1/ask", body, timeout=180)


def said(e: Any) -> str:
    """A ClientError, in the person's words."""
    if e.status == 409 and e.title == "voice is off":
        return "Voice is off: choose a speech model in Handler, Settings → Expert → Voice."
    return e.detail or str(e)


# ── --check ──────────────────────────────────────────────────────────────────────────────────


def checked() -> int:
    """What this computer will use, and whether Handler can write down and route what you say.
    1 when something is missing for `--toggle` to work. Run by a key (no terminal), the answer is
    also a sound and a notification: the key's setup is not the terminal's (a Flatpak's, say)."""
    dev = vd.device()
    lines = checks(dev)
    for line, _ in lines:
        print(line)
    missing = [line.strip() for line, problem in lines if problem]
    if not sys.stdout.isatty():
        body = "\n".join(missing) or "Ready: press, speak, press again."
        heard(dev, "failed" if missing else "done", "Handler · voice check", body)
    return 1 if missing else 0


def checks(dev: vd.Device) -> list[tuple[str, bool]]:
    """`--check`'s lines, each with whether it is a problem for `--toggle`."""
    names = {"linux": "Linux", "macos": "macOS", "wsl": "WSL"}
    lines = [(names[dev.system], False)]
    if dev.system == "wsl":
        lines.append(
            ("  WSL is not tested: sounds through WSLg, no notifications on Windows", False)
        )
    for what, label, needed in (
        ("recorder", "recording", True),
        ("player", "sounds", dev.notifier is None),
        ("notifier", "notifications", dev.player is None),
    ):
        found = getattr(dev, what)
        if found:
            lines.append((f"  {label}: {found}", False))
        elif dev.system == "macos" and what == "recorder":
            lines.append(("  recording: missing: reinstall Handler (it brings sounddevice)", True))
        else:
            lines.append((f"  {label}: missing: install {INSTALL[what]}", needed))
    from .client import ClientError, Daemon, httpx  # noqa: PLC0415

    try:
        daemon = Daemon()
        voice = daemon.call("GET", "/v1/voice")
        needs = daemon.call("GET", "/v1/handler-needs")
    except ClientError as e:
        return [*lines, (f"Handler: {e}", True)]
    except httpx.HTTPError:
        return [*lines, ("Handler: not answering: is it running?", True)]
    if voice.get("model") and not voice.get("problem"):
        lines.append((f"Voice: {voice['model']}", False))
    else:
        problem = voice.get("problem") or "off"
        lines.append(
            (f"Voice: {problem}: choose a speech model in Settings → Expert → Voice", True)
        )
    router = next((n for n in needs if n["name"] == "ask-router"), None)
    if router and router.get("agentId"):
        lines.append(("Ask's router: set", False))
    else:
        lines.append(("Ask's router: not set: turn it on in Handler, Chat → Ask", True))
    return lines
