"""Plain-text output shared by the commands."""

from typing import Any


def one_line(text: str, width: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def table(rows: list[list[str]]) -> None:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(r, widths, strict=True)).rstrip())


def refused_hosts(hosts: list[dict[str, Any]]) -> str:
    """Hosts the network filter refused (F.9): "pypi.org:443 (3 times), x.org:443 (once, allowed)"."""

    def one(h: dict[str, Any]) -> str:
        times = "once" if h["count"] == 1 else f"{h['count']} times"
        return f"{h['host']} ({times}{', ' + h['decision'] if h.get('decision') else ''})"

    return ", ".join(one(h) for h in hosts)
