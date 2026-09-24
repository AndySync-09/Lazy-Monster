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


WORK_TOOLS = {"write_in_app", "type_text", "word_insert_text", "word_save", "code_write_file", "code_run",
              "make_presentation", "export_pdf", "web_research", "open_file", "file_write_text", "close_all"}
_FOLLOWUP = re.compile(r"^\s*(yes|yeah|sure|ok(ay)?)?[,.!\s]*please do that\b", re.I)


def worth_keeping(task: str, tools: List[str]) -> bool:
    """Only real work goes in the journal: not "mute", not an accepted suggestion echo."""
    if _FOLLOWUP.match(task or "") or len((task or "").split()) < 3:
        return False
    return bool(set(tools or []) & WORK_TOOLS)


def add(task: str, summary: str, files: List[str], tools: List[str] = None) -> None:
    if tools is not None and not worth_keeping(task, tools):
        return
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


def _clean_summary(s: str) -> str:
    s = re.sub(r"^\s*(done|okay|ok|sure|all set)[.!,:\s\u2014-]*", "", s or "", flags=re.I).strip()
    s = re.split(r"(?<=[.!?])\s", s)[0].rstrip(".!? ")                 # first sentence only
    if not s or re.match(r"I\b", s):
        return s
    return s[:1].lower() + s[1:]


def recap(rows=None) -> str:
    rows = recent() if rows is None else rows
    rows = [r for r in rows if not _FOLLOWUP.match(r.get("task", "")) and len(r.get("task", "").split()) >= 3]
    items = []
    for r in reversed(rows):
        s = _clean_summary(r.get("summary", "")) or short_task(r["task"])
        if s and s not in items:
            items.append(s)
        if len(items) == 2:
            break
    if not items:
        return ""
    if len(items) == 1:
        return f"Last time, {items[0]}."
    return f"Last time, {items[0]}. Before that, {items[1]}."


def context(rows=None) -> str:
    rows = recent() if rows is None else rows
    if not rows:
        return ""
    lines = [f"- {time.strftime('%a %d %b %H:%M', time.localtime(r['ts']))}: {r['task']}"
             + (f" (files: {', '.join(r['files'])})" if r.get("files") else "") for r in rows]
    return "Earlier work with this user (use it to resume if they ask):\n" + "\n".join(lines)
