"""Ask's history (D.24): each ask Handler received, from any place (Chat's Ask tab, a phone,
`handler ask`, a key), with what was said, where it went and how it ended, so "did it work?" is
answered after the fact. Text only: the recording is never kept (rule voice.never-kept).

    <state>/asks.json     {"keep": bool, "asks": [AskRecord…]}, oldest first

The last KEEP asks, none older than DAYS. Off (`keep` false), nothing is kept and what was is
emptied. An ask that failed or that no app does is also told to the inbox (Assistant).
"""

import contextlib
import json
import secrets
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from handler_contracts import AskHistory, AskOutcome, AskRecord, AskTurn, AskVia, AssistantAnswer

from .settings import Settings

KEEP = 200
DAYS = 30


def outcome(answer: AssistantAnswer) -> tuple[AskOutcome, str]:
    """How an answer ended, and its sentence: the app's, the question, why no app fits."""
    if answer.kind == "needs":
        return "question", answer.question or answer.summary
    if answer.kind == "none" or answer.run is None:
        return "none", answer.summary
    run = answer.run
    if run.state == "running":
        return "running", "Its job is on it: its answer comes to your inbox."
    if run.state == "failed" or run.result is None:
        return "failed", run.error or "It failed."
    status = run.result.status
    kind: AskOutcome = (
        "done" if status == "ok" else "attention" if status == "attention" else "failed"
    )
    return kind, run.result.summary


class AskHistoryStore:
    def __init__(self, settings: Settings) -> None:
        self.file = settings.state_dir / "asks.json"
        self.keep = True
        self.asks: list[AskRecord] = []
        self.watchers: list[Callable[[], None]] = []  # told after each save (D.30, topic "ask")
        self.lock = threading.Lock()
        with contextlib.suppress(FileNotFoundError, ValueError, ValidationError):
            raw = json.loads(self.file.read_text())
            self.keep = bool(raw["keep"])
            self.asks = [AskRecord.model_validate(a) for a in raw["asks"]]

    def add(
        self,
        via: AskVia,
        spoken: bool,
        turns: list[AskTurn],
        answer: AssistantAnswer | None = None,
        error: str | None = None,
    ) -> AskRecord:
        """One ask, as it ended: Ask's answer, or why it could not answer (`error`). Kept only
        while the history is on; given back either way."""
        if answer is not None:
            kind, summary = outcome(answer)
        else:
            kind, summary = "failed", error or "Ask could not answer."
        record = AskRecord(
            id=secrets.token_hex(8),
            at=datetime.now(UTC),
            via=via,
            spoken=spoken,
            turns=turns,
            outcome=kind,
            summary=summary,
            answer=answer,
        )
        if self.keep:
            with self.lock:
                self.asks = _kept([*self.asks, record])
                self._save()
        return record

    def ended(self, record_id: str, answer: AssistantAnswer) -> None:
        """A job's action that was running has ended: its record says how."""
        kind, summary = outcome(answer)
        with self.lock:
            for i, a in enumerate(self.asks):
                if a.id == record_id:
                    change = {"answer": answer, "outcome": kind, "summary": summary}
                    self.asks[i] = a.model_copy(update=change)
                    self._save()
                    return

    def view(self) -> AskHistory:
        cutoff = datetime.now(UTC) - timedelta(days=DAYS)
        asks = [a for a in reversed(self.asks) if a.at >= cutoff]
        return AskHistory(keep=self.keep, asks=asks)

    def set_keep(self, keep: bool) -> AskHistory:
        with self.lock:
            self.keep = keep
            if not keep:
                self.asks = []
            self._save()
        return self.view()

    def delete(self, record_id: str) -> bool:
        with self.lock:
            kept = [a for a in self.asks if a.id != record_id]
            if len(kept) == len(self.asks):
                return False
            self.asks = kept
            self._save()
            return True

    def clear(self) -> None:
        with self.lock:
            self.asks = []
            self._save()

    def _save(self) -> None:
        data = {
            "keep": self.keep,
            "asks": [
                a.model_dump(mode="json", by_alias=True, exclude_none=True) for a in self.asks
            ],
        }
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.chmod(0o600)
        tmp.replace(self.file)
        for watcher in self.watchers:
            watcher()


def _kept(asks: list[AskRecord]) -> list[AskRecord]:
    """The last KEEP asks, none older than DAYS, oldest first."""
    cutoff = datetime.now(UTC) - timedelta(days=DAYS)
    return [a for a in asks if a.at >= cutoff][-KEEP:]
