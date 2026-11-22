"""`handler ask --listen` (handler_cli/listen.py, voice_device.py): press to start, press to stop;
what was said written down and asked; how it went, a sound and a notification; a question back
answered by the next press, the exchange in memory only. The computer's side is faked (no
microphone in CI): its recorder, its player and its notifications."""

import argparse
import base64
import io
import subprocess
import sys
import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from handler_cli import client, listen
from handler_cli import voice_device as vd

ONE_SECOND = vd.wav(bytes(vd.RATE * 2), vd.RATE, 1)


class Computer:
    """This computer, faked: what was played and notified, each recording started."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.sounds: list[str] = []
        self.notified: list[tuple[str, str]] = []
        self.recording = threading.Event()  # set while one records
        self.recordings = 0
        self.audio = ONE_SECOND
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        self.dev = vd.Device("linux", "pw-record", "pw-play", "notify-send")
        monkeypatch.setattr(vd, "device", lambda: self.dev)
        monkeypatch.setattr(vd, "record", self.record)
        monkeypatch.setattr(vd, "play", lambda _dev, name: self.sounds.append(name))
        monkeypatch.setattr(vd, "notify", lambda _dev, t, b: self.notified.append((t, b)))

    def record(self, _dev: vd.Device) -> Any:
        computer = self
        self.recordings += 1
        self.recording.set()

        class Recording:
            def stop(self) -> bytes:
                computer.recording.clear()
                return computer.audio

        return Recording()


class Handler:
    """handlerd, answering /v1/voice/transcribe with what is said, /v1/ask in turn."""

    def __init__(self, said: list[str], *answers: dict[str, Any]) -> None:
        self.said = said
        self.answers = list(answers)
        self.calls: list[tuple[str, Any]] = []

    def __call__(self) -> "Handler":
        return self

    def call(self, method: str, path: str, body: Any = None, **_: Any) -> dict[str, Any]:
        self.calls.append((path, body))
        if path == "/v1/voice/transcribe":
            return {"text": self.said.pop(0)}
        return self.answers.pop(0)


def pick(
    status: str = "ok", summary: str = "Moved Dentist to Monday 23 November at 10:00."
) -> dict[str, Any]:
    run = {"runId": "r1", "state": "succeeded", "result": {"status": status, "summary": summary}}
    return {"kind": "pick", "app": "Planner", "action": "move", "summary": "s", "run": run}


def press_when(ready: Callable[[], bool], presses: int = 1) -> threading.Thread:
    """Another press of the key, each once `ready()` holds: as a second `handler ask --listen
    --toggle` would, in this process (the lock is per open file: it is held for it too)."""

    def go() -> None:
        for _ in range(presses):
            deadline = time.monotonic() + 5
            while not ready() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert listen.pressed() == 0
            time.sleep(0.05)

    thread = threading.Thread(target=go)
    thread.start()
    return thread


@pytest.fixture
def computer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Computer:
    return Computer(monkeypatch, tmp_path)


@pytest.mark.rule("voice.cli-press-to-start-press-to-stop", "voice.cli-outcome-heard")
def test_a_second_press_stops_it_and_how_it_went_is_heard(
    computer: Computer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first press records (its sound at once); the next one stops it ("got it" at once):
    what was said is written down, asked, and the app's answer is a sound and a notification
    naming what was heard.

    If this fails: a key's second press starts another recording, or nothing says how it went."""
    handler = Handler(["move the dentist to Monday 10:00"], pick())
    monkeypatch.setattr(client, "Daemon", handler)
    other = press_when(computer.recording.is_set)
    assert listen.pressed() == 0
    other.join()
    assert computer.sounds == ["start", "heard", "done"]
    assert computer.notified == [
        (
            "Planner · move",
            "Moved Dentist to Monday 23 November at 10:00.\n"
            "Heard: “move the dentist to Monday 10:00”",
        )
    ]
    (path, body), (ask_path, asked) = handler.calls
    assert (path, body["format"]) == ("/v1/voice/transcribe", "wav")
    assert base64.b64decode(body["audio"]) == ONE_SECOND
    assert ask_path == "/v1/ask"
    assert asked["turns"] == [{"who": "you", "text": "move the dentist to Monday 10:00"}]


@pytest.mark.rule("voice.cli-press-to-start-press-to-stop", "voice.cli-keeps-nothing")
def test_a_question_back_is_answered_by_the_next_press_and_kept_in_memory_only(
    computer: Computer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ask asks back: its sound and the question; the next press records the answer, the one
    after stops it, and the whole exchange is asked. Nothing of it is ever on disk.

    If this fails: an answer to Ask's question is asked alone (meaningless), or what you said
    is left in a file."""
    question = {"kind": "needs", "summary": "To which day?", "question": "To which day?"}
    handler = Handler(["move the dentist", "Monday"], question, pick())
    monkeypatch.setattr(client, "Daemon", handler)
    asked_back = lambda: ("Handler asks", "To which day?\nPress to answer.") in computer.notified  # noqa: E731
    first = press_when(computer.recording.is_set)
    assert_files_hold_nothing_said = []

    def answer() -> None:
        first.join()
        deadline = time.monotonic() + 5
        while not asked_back() and time.monotonic() < deadline:
            time.sleep(0.01)
        for f in tmp_path.rglob("*"):  # while the listener waits for the answer
            if f.is_file():
                assert_files_hold_nothing_said.append(b"dentist" in f.read_bytes())
        assert listen.pressed() == 0  # records the answer
        deadline = time.monotonic() + 5
        while not computer.recording.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert listen.pressed() == 0  # stops it

    second = threading.Thread(target=answer)
    second.start()
    assert listen.pressed() == 0
    second.join()
    assert computer.sounds == ["start", "heard", "question", "start", "heard", "done"]
    assert computer.recordings == 2
    assert handler.calls[-1][1]["turns"] == [
        {"who": "you", "text": "move the dentist"},
        {"who": "handler", "text": "To which day?"},
        {"who": "you", "text": "Monday"},
    ]
    assert assert_files_hold_nothing_said and not any(assert_files_hold_nothing_said)


@pytest.mark.rule("voice.cli-outcome-heard")
@pytest.mark.parametrize(
    "case",
    [
        ([""], None, None, ("failed", "Nothing heard", "Press, speak, press again.")),
        (
            ["book a table"],
            {"kind": "none", "summary": "None of your apps books tables."},
            None,
            ("failed", "No app does that", "“book a table”: None of your apps books tables."),
        ),
        (
            ["x"],
            None,
            client.ClientError("409 voice is off", 409, "voice is off", "no speech model"),
            (
                "failed",
                "Ask could not answer",
                "Voice is off: choose a speech model in Handler, Settings → Expert → Voice.",
            ),
        ),
        (
            ["which one"],
            pick("attention", "Which one? Nothing changed."),
            None,
            ("attention", "Planner · move", "Which one? Nothing changed.\nHeard: “which one”"),
        ),
        (
            ["plan my day"],
            {
                "kind": "pick",
                "app": "Planner",
                "action": "plan",
                "run": {"runId": "r", "state": "running"},
            },
            None,
            (
                "done",
                "Planner · plan",
                "Its job is on it: its answer comes to your inbox.\nHeard: “plan my day”",
            ),
        ),
    ],
)
def test_each_end_is_its_sound_and_what_it_says(
    computer: Computer,
    monkeypatch: pytest.MonkeyPatch,
    case: tuple[list[str], dict[str, Any] | None, Exception | None, tuple[str, str, str]],
) -> None:
    """Nothing heard, no app for it, voice off: the error tone and why; done with something to
    read: its own sound; a job's action: done once its run started, its answer in the inbox.

    If this fails: you hear "done" for what was not done, or nothing at all."""
    said, answer, error, heard = case
    handler = Handler(said, *([answer] if answer else []))
    if error is not None:

        def fails(*_: Any, **__: Any) -> Any:
            raise error

        handler.call = fails  # ty: ignore[invalid-assignment]
    monkeypatch.setattr(client, "Daemon", handler)
    other = press_when(computer.recording.is_set)
    code = listen.pressed()
    other.join()
    kind, title, body = heard
    assert computer.sounds == ["start", "heard", kind]
    assert computer.notified == [(title, body)]
    assert code == (1 if kind == "failed" else 0)


@pytest.mark.rule("voice.cli-outcome-heard", "voice.cli-keeps-nothing")
@pytest.mark.parametrize(
    "error, title",
    [
        (KeyError("summary"), "The listener failed"),
        (client.httpx.ConnectError("refused"), "Handler did not answer"),
    ],
)
def test_whatever_ends_it_is_heard_and_what_handler_did_not_see_is_logged(
    computer: Computer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error: Exception,
    title: str,
) -> None:
    """A listener failing in a way nobody foresaw, or Handler not answering: still the error
    tone and a notification, and a line in the log, never with what was said.

    If this fails: a press ends in silence, and nothing tells you why afterwards."""
    handler = Handler(["call the bank tomorrow"])

    def asks(*_: Any, **__: Any) -> Any:
        raise error

    monkeypatch.setattr(listen, "asked", asks)
    monkeypatch.setattr(client, "Daemon", handler)
    other = press_when(computer.recording.is_set)
    assert listen.pressed() == 1
    other.join()
    assert computer.sounds == ["start", "heard", "failed"]
    assert computer.notified[0][0] == title
    log = (tmp_path / "state" / "handler-ai" / "listen.log").read_text()
    assert title in log and type(error).__name__ in log
    assert "bank" not in log


@pytest.mark.rule("voice.cli-outcome-heard")
def test_no_recorder_is_heard_before_anything_is_loaded(
    computer: Computer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recorder failing to start, before the client is loaded: said, not a crash."""

    def no_recorder(_dev: vd.Device) -> Any:
        raise FileNotFoundError("pw-record")

    monkeypatch.setattr(vd, "record", no_recorder)
    assert listen.pressed() == 1
    assert computer.sounds == ["failed"]
    assert computer.notified[0][0] == "No recorder"


def test_check_run_by_a_key_is_heard(
    computer: Computer, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--check` given to a key (no terminal): a sound and a notification say what the key's
    own setup lacks, or that it is ready."""
    computer.dev = vd.Device("linux", "pw-record", "pw-play", "notify-send")

    class Answers:
        def call(self, _m: str, path: str, *_: Any, **__: Any) -> Any:
            return {"model": "m"} if path == "/v1/voice" else [{"name": "ask-router"}]

    monkeypatch.setattr(client, "Daemon", Answers)
    assert listen.run(toggle=False, check=True) == 1
    assert computer.sounds == ["failed"]
    assert computer.notified == [
        ("Handler · voice check", "Ask's router: not set: turn it on in Handler, Chat → Ask")
    ]


def test_too_short_is_nothing_heard_and_not_sent(
    computer: Computer, monkeypatch: pytest.MonkeyPatch
) -> None:
    computer.audio = vd.wav(bytes(vd.RATE // 10 * 2), vd.RATE, 1)  # 0.1 s: a press and a press
    handler = Handler([])
    monkeypatch.setattr(client, "Daemon", handler)
    other = press_when(computer.recording.is_set)
    assert listen.pressed() == 1
    other.join()
    assert handler.calls == [] and computer.notified[0][0] == "Nothing heard"


def test_an_unanswered_question_ends_it(
    computer: Computer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(listen, "QUESTION_WAIT", 0.2)
    question = {"kind": "needs", "summary": "?", "question": "Which one?"}
    monkeypatch.setattr(client, "Daemon", Handler(["call"], question))
    other = press_when(computer.recording.is_set)
    assert listen.pressed() == 1
    other.join()
    assert computer.sounds == ["start", "heard", "question"] and computer.recordings == 1


def test_a_recorder_s_wav_is_made_right_and_cut_at_its_longest() -> None:
    """A recorder stopped may leave its sizes unwritten: the samples are read to the end."""
    frames = bytes(range(256)) * 4
    good = vd.wav(frames, 16000, 1)
    unwritten = good[:4] + b"\x00\x00\x00\x00" + good[8:40] + b"\xff\xff\xff\xff" + good[44:]
    with wave.open(io.BytesIO(vd.clean_wav(unwritten))) as w:
        assert (w.getframerate(), w.getnchannels(), w.readframes(10_000)) == (16000, 1, frames)
    longest = vd.wav(bytes(vd.RATE * 2 * (vd.MAX_SECONDS + 5)), vd.RATE, 1)
    assert vd.seconds(vd.clean_wav(longest)) == vd.MAX_SECONDS
    assert len(vd.clean_wav(longest)) < 1024 * 1024  # under handlerd's MAX_AUDIO
    assert vd.clean_wav(b"not a wav") == b""


def test_its_sounds_are_made_once_as_wav(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    for name in vd.SOUNDS:
        path = vd.sound(name)
        assert 0.1 < vd.seconds(path.read_bytes()) < 1
        assert vd.sound(name) == path
    assert (vd.workdir().stat().st_mode & 0o777) == 0o700


def test_check_says_what_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(vd, "device", lambda: vd.Device("linux", None, "paplay", None))
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)

    class Answers:
        def call(self, _m: str, path: str, *_: Any, **__: Any) -> Any:
            return (
                {"model": None}
                if path == "/v1/voice"
                else [{"name": "ask-router", "agentId": "a1"}]
            )

    monkeypatch.setattr(client, "Daemon", Answers)
    assert listen.run(toggle=False, check=True) == 1
    out = capsys.readouterr().out
    assert "recording: missing: install PipeWire (pw-record)" in out
    assert "sounds: paplay" in out and "notifications: missing" in out
    assert "Voice: off: choose a speech model in Settings → Expert → Voice" in out
    assert "Ask's router: set" in out


def test_listening_starts_before_the_client_is_loaded() -> None:
    """The fast path (entry.py) reaches listen.py with nothing heavy loaded: the recording
    starts a few tens of milliseconds after the key, not a quarter of a second.

    If this fails: the first words said after the key are lost."""
    code = (
        "import sys, handler_cli.entry, handler_cli.listen; "
        "print(sorted(m for m in ('httpx', 'handler_cli.cli', 'handler_cli.client', 'pydantic') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_toggle_and_check_go_with_listen() -> None:
    from handler_cli import ask_commands  # noqa: PLC0415

    for flags in ({"toggle": True}, {"check": True}):
        args = argparse.Namespace(words=[], listen=False, toggle=False, check=False, history=False)
        vars(args).update(flags)
        with pytest.raises(SystemExit, match="go with --listen"):
            ask_commands.dispatch(args)
    args = argparse.Namespace(words=["hi"], listen=True, toggle=False, check=False, history=False)
    with pytest.raises(SystemExit, match="no words with it"):
        ask_commands.dispatch(args)


def test_the_command_ends_with_what_it_answered(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `handler` command's entry gives back the CLI's exit code, and --listen's.

    If this fails: every failure of `handler` ends in success, for scripts and keys alike."""
    from handler_cli import cli, entry  # noqa: PLC0415

    monkeypatch.setattr(cli, "main", lambda: 3)
    monkeypatch.setattr(sys, "argv", ["handler", "image", "list"])
    assert entry.main() == 3
    monkeypatch.setattr(listen, "run", lambda **_: 1)
    monkeypatch.setattr(sys, "argv", ["handler", "ask", "--listen", "--toggle"])
    assert entry.main() == 1
