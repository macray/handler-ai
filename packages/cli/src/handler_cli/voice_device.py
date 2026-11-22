"""What `handler ask --listen` needs of this computer: record from the microphone, play a short
sound, show a notification. Linux (and WSL, through WSLg) by the programs it has (PipeWire,
PulseAudio, ALSA, `notify-send`); macOS by `sounddevice` (PortAudio inside its wheel), `afplay`
and `osascript`. Only `listen.py` uses it; it never talks to handlerd.

Light on purpose: `listen.py` starts recording before the rest of the CLI is loaded.

A recording is 16 kHz mono 16-bit WAV, at most MAX_SECONDS: 32 KB a second, under handlerd's
1 MiB (MAX_AUDIO). On Linux the recorder writes it to `workdir()` (the user's runtime folder,
in memory, 0700), read back and deleted when it stops; on macOS it stays in memory.
"""

import io
import math
import os
import shutil
import signal
import struct
import subprocess
import sys
import threading
import wave
from collections.abc import Buffer
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

RATE = 16000
MAX_SECONDS = 30
SOUND_RATE = 22050

# Linux: the first of each found, with what it is given (PipeWire, then PulseAudio, then ALSA)
RECORDERS: dict[str, list[str]] = {
    "pw-record": ["--rate", str(RATE), "--channels", "1", "--format", "s16"],
    "parecord": [f"--rate={RATE}", "--channels=1", "--format=s16le", "--file-format=wav"],
    "arecord": ["-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "wav"],
}
PLAYERS = ("pw-play", "paplay", "aplay")


@dataclass(frozen=True)
class Device:
    """What this computer will use; None: it has none (`--check` says what to install)."""

    system: str  # "linux", "wsl", "macos"
    recorder: str | None
    player: str | None
    notifier: str | None


def system() -> str:
    if sys.platform == "darwin":
        return "macos"
    try:
        return "wsl" if "microsoft" in Path("/proc/version").read_text().lower() else "linux"
    except OSError:
        return "linux"


def device() -> Device:
    name = system()
    if name == "macos":
        try:
            import sounddevice  # noqa: F401, PLC0415
        except (ImportError, OSError):
            recorder = None
        else:
            recorder = "sounddevice"
        return Device(name, recorder, "afplay", "osascript")
    recorder = next((r for r in RECORDERS if shutil.which(r)), None)
    player = next((p for p in PLAYERS if shutil.which(p)), None)
    return Device(name, recorder, player, "notify-send" if shutil.which("notify-send") else None)


def workdir() -> Path:
    """Where the recording (Linux) and the sounds are, while `--listen` runs: the user's runtime
    folder (in memory on Linux), a folder of its own, 0700."""
    base = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    path = Path(base) / f"handler-listen-{os.getuid()}"
    path.mkdir(mode=0o700, exist_ok=True)
    if path.stat().st_uid != os.getuid() or path.is_symlink():
        raise OSError(f"{path} is not yours")
    path.chmod(0o700)
    return path


# ── recording ────────────────────────────────────────────────────────────────────────────────


class Recording(Protocol):
    def stop(self) -> bytes:
        """Stop, and give what was recorded as WAV (at most MAX_SECONDS)."""
        ...


def record(dev: Device) -> Recording:
    """Start recording now."""
    if dev.recorder is None:
        raise OSError("no recorder")
    if dev.recorder == "sounddevice":
        return _MacRecording()
    return _ProgramRecording(dev.recorder, workdir() / "recording.wav")


class _ProgramRecording:
    """A recorder program writing a WAV file, stopped as Ctrl-C would."""

    def __init__(self, program: str, path: Path) -> None:
        self.path = path
        path.unlink(missing_ok=True)
        self.process = subprocess.Popen(
            [program, *RECORDERS[program], str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> bytes:
        try:
            if self.process.poll() is None:
                self.process.send_signal(signal.SIGINT)
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            try:
                return clean_wav(self.path.read_bytes())
            except FileNotFoundError:
                return b""
        finally:
            self.path.unlink(missing_ok=True)


class _MacRecording:
    """macOS: PortAudio through sounddevice, into memory."""

    def __init__(self) -> None:
        import sounddevice  # noqa: PLC0415

        self.chunks: list[bytes] = []
        self.size = 0
        self.lock = threading.Lock()
        self.stream = sounddevice.RawInputStream(
            samplerate=RATE, channels=1, dtype="int16", callback=self._take
        )
        self.stream.start()

    def _take(self, data: Buffer, _frames: int, _time: object, _status: object) -> None:
        with self.lock:
            if self.size < RATE * 2 * MAX_SECONDS:
                chunk = bytes(data)
                self.chunks.append(chunk)
                self.size += len(chunk)

    def stop(self) -> bytes:
        self.stream.stop()
        self.stream.close()
        with self.lock:
            return wav(b"".join(self.chunks), RATE, 1)


def wav(frames: bytes, rate: int, channels: int) -> bytes:
    """16-bit samples as a WAV file, cut at MAX_SECONDS."""
    frames = frames[: rate * channels * 2 * MAX_SECONDS]
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return out.getvalue()


def clean_wav(data: bytes) -> bytes:
    """A recorder's WAV made right: a recorder stopped may leave its sizes unwritten (0, or the
    largest), so its samples are taken to the file's end and written again, cut at MAX_SECONDS.
    Not 16-bit PCM, or no samples: b""."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return b""
    at, fmt = 12, None
    while at + 8 <= len(data):
        kind, size = data[at : at + 4], struct.unpack("<I", data[at + 4 : at + 8])[0]
        if kind == b"fmt ":
            fmt = struct.unpack("<HHIIHH", data[at + 8 : at + 24])
        if kind == b"data":
            if fmt is None or fmt[0] != 1 or fmt[5] != 16:  # PCM, 16-bit
                return b""
            frames = data[at + 8 :]
            frames = frames[: len(frames) - len(frames) % (2 * fmt[1])]
            return wav(frames, fmt[2], fmt[1]) if frames else b""
        at += 8 + size + size % 2
    return b""


def seconds(recording: bytes) -> float:
    """How long a WAV made here lasts."""
    if not recording:
        return 0.0
    with wave.open(io.BytesIO(recording)) as w:
        return w.getnframes() / w.getframerate()


# ── sounds and notifications ────────────────────────────────────────────────────────────────

# each sound: its notes (Hz, seconds); a glide is a note from one pitch to the next
SOUNDS: dict[str, list[tuple[float, float, float]]] = {
    "start": [(660, 990, 0.12)],  # rising: listening
    "heard": [(990, 660, 0.08)],  # falling, short: got it, stopped; how it went comes next
    "done": [(880, 880, 0.09), (1320, 1320, 0.14)],
    "attention": [(740, 740, 0.1), (740, 740, 0.1)],  # done, with something to read
    "question": [(523, 523, 0.1), (784, 784, 0.16)],  # the next press answers it
    "failed": [(392, 392, 0.16), (262, 262, 0.24)],  # falling
}


def sound(name: str) -> Path:
    """The file of one of SOUNDS, made once (our own tones, no file shipped)."""
    path = workdir() / f"{name}.wav"
    if path.exists():
        return path
    frames = bytearray()
    for start, end, length in SOUNDS[name]:
        n = int(SOUND_RATE * length)
        phase = 0.0
        for i in range(n):
            phase += 2 * math.pi * (start + (end - start) * i / n) / SOUND_RATE
            fade = min(1.0, i / 200, (n - i) / 400)  # no click at either end
            frames += struct.pack("<h", int(0.3 * 32767 * fade * math.sin(phase)))
        frames += bytes(int(SOUND_RATE * 0.03) * 2)  # a breath between notes
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(wav(bytes(frames), SOUND_RATE, 1))
    tmp.replace(path)
    return path


def play(dev: Device, name: str) -> subprocess.Popen[bytes] | None:
    """Play a sound without waiting for it; nothing when there is no player."""
    if dev.player is None:
        return None
    return subprocess.Popen(
        [dev.player, str(sound(name))],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def notify(dev: Device, title: str, body: str) -> None:
    """A notification on the desktop; nothing when there is no way to show one."""
    if dev.notifier == "notify-send":
        command = ["notify-send", "--app-name=Handler", title, body]
    elif dev.notifier == "osascript":  # the words as arguments: never read as a script
        script = [
            "on run argv",
            "display notification (item 2 of argv) with title (item 1 of argv)",
            "end run",
        ]
        command = ["osascript", *(a for line in script for a in ("-e", line)), title, body]
    else:
        return
    subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False)
