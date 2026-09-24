"""Pure text helpers: paste chunking and read-back verification."""
import re
from typing import List, Tuple


def paste_lines(text: str) -> List[str]:
    """Lines to paste one by one (Enter is pressed between them), so the
    document fills visibly and newlines are real key presses."""
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _norm(s: str) -> str:
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def verify(intended: str, actual: str) -> Tuple[bool, str]:
    """Did the intended text land in the document? Tolerant of whitespace,
    smart quotes and auto-formatting; strict about the words themselves."""
    want, got = _norm(intended), _norm(actual)
    if not want:
        return True, "nothing to verify"
    if want in got:
        return True, "verified: the document contains the text"
    words = want.split()
    found = sum(1 for w in words if w in got)
    ratio = found / len(words)
    if ratio >= 0.97 and len(got) <= len(want) * 1.6 + 40:
        return True, f"verified ({ratio:.0%} of words match; minor auto-formatting)"
    snippet = actual.strip().replace("\n", " / ")[:300]
    return False, (f"MISMATCH: only {ratio:.0%} of the words are in the document. "
                   f"It currently contains: \"{snippet}\". Fix it (select all and write again) or ask_user.")


CANDIDATES = re.compile(r"\{\s*\"candidates\"\s*:\s*\[.*?\]\s*\}", re.S)


def parse_candidates(content) -> list:
    """The agent may put {"candidates":[{"tool":..., "p":0.6}, ...]} in its
    message; the UI draws these as decision branches. Missing or malformed is fine."""
    import json
    if not isinstance(content, str):
        return []
    m = CANDIDATES.search(content)
    if not m:
        return []
    try:
        items = json.loads(m.group(0)).get("candidates", [])
    except (ValueError, AttributeError):
        return []
    out = []
    for it in items[:4]:
        if isinstance(it, dict) and isinstance(it.get("tool"), str):
            try:
                p = float(it.get("p", 0))
            except (TypeError, ValueError):
                p = 0.0
            out.append({"tool": it["tool"][:40], "p": max(0.0, min(1.0, p))})
    return out


def sentences(text: str, max_len: int = 220) -> List[str]:
    """Split speech into sentences so the first one can play while the next renders."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out = []
    for p in parts:
        while len(p) > max_len:
            cut = p.rfind(",", 0, max_len)
            cut = cut if cut > 40 else max_len
            out.append(p[:cut + 1].strip())
            p = p[cut + 1:]
        if p.strip():
            out.append(p.strip())
    return out
