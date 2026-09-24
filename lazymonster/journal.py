"""What we worked on: one line per finished task, kept locally in
%APPDATA%\\lazymonster\\journal.jsonl. Used for "welcome back" recaps and so the
agent can resume ("carry on with the snake game")."""
import json
import re
import time
from pathlib import Path
from typing import List

from .config import config_dir

_PATH = re.compile(r"(?:saved|wrote \d+ lines to|into|to) ([A-Za-z]:\\[^;,\n]+?\.[A-Za-z0-9]{1,6})")
_FILLER = re.compile(r"^(?:hey monster[,.!]?\s*|can you\s+|could you\s+|please\s+|i want you to\s+|i'd like you to\s+)+", re.I)


def path() -> Path:
    return config_dir() / "journal.jsonl"


def files_in(texts: List[str]) -> List[str]:
    out = []
    for t in texts:
        out += [m.strip() for m in _PATH.findall(t or "")]
    return list(dict.fromkeys(out))[:6]


def add(task: str, summary: str, files: List[str]) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "task": task[:300], "summary": summary[:300], "files": files}) + "\n")


def recent(days: float = 7, n: int = 5) -> list:
    p = path()
    if not p.exists():
        return []
    cutoff, rows = time.time() - days * 86400, []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("ts", 0) >= cutoff and r.get("task"):
            rows.append(r)
    return rows[-n:]


def short_task(task: str) -> str:
    t = _FILLER.sub("", task.strip()).rstrip(".?! ")
    words = t.split()
    return " ".join(words[:9]) + ("…" if len(words) > 9 else "")


def recap(rows=None) -> str:
    rows = recent() if rows is None else rows
    items = list(dict.fromkeys(short_task(r["task"]) for r in reversed(rows) if len(r["task"].split()) >= 3))[:3]
    if not items:
        return ""
    if len(items) == 1:
        return f"Last time we worked on: {items[0]}."
    return "Recently we worked on: " + ", ".join(items[:-1]) + f", and {items[-1]}."


def context(rows=None) -> str:
    rows = recent() if rows is None else rows
    if not rows:
        return ""
    lines = [f"- {time.strftime('%a %d %b %H:%M', time.localtime(r['ts']))}: {r['task']}"
             + (f" (files: {', '.join(r['files'])})" if r.get("files") else "") for r in rows]
    return "Earlier work with this user (use it to resume if they ask):\n" + "\n".join(lines)
