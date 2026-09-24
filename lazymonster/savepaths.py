"""Where things get saved when you close them: the name and place you say, or
your default save folder (C:\\temp unless you change `default_save_dir`)."""
import os
import re
from pathlib import Path
from typing import Optional, Tuple

NO = re.compile(r"^\W*(no|nope|don'?t( save)?|do not save|discard|throw (it|them) away|skip( it)?|delete it|close without saving)\b", re.I)
YES_ONLY = re.compile(r"^\W*(yes|yeah|yep|sure|ok(ay)?|save( it)?|please( do)?|go ahead|do it)\W*$", re.I)
NAMED = re.compile(r"(?:save (?:it |this )?as|call it|name it|named|as)\s+(.+)$", re.I)
PLACES = {"desktop": "Desktop", "documents": "Documents", "document": "Documents", "downloads": "Downloads",
          "download": "Downloads", "temp": "TEMP", "c temp": "TEMP", "pictures": "Pictures"}


def known_folder(word: str, default_dir: str) -> Path:
    if word == "TEMP":
        return Path(default_dir)
    home = Path.home()
    od = home / "OneDrive" / word
    return od if od.is_dir() else home / word


def slug(text: str, fallback: str = "untitled") -> str:
    s = re.sub(r"[^A-Za-z0-9 _-]+", "", text).strip().replace(" ", "-").lower()
    s = re.sub(r"-{2,}", "-", s)[:60].strip("-")
    return s or fallback


def interpret(answer: str, suggested: str, default_dir: str) -> Tuple[str, Optional[Path]]:
    """-> ("discard", None) | ("save", path) | ("save", None) meaning use the default.
    The name is yours if you gave one; otherwise the suggested one."""
    a = (answer or "").strip()
    if NO.match(a):
        return "discard", None
    folder = Path(default_dir)
    low = a.lower()
    for k, v in sorted(PLACES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b(?:in|to|on|into)\s+(?:my\s+|the\s+)?{k}\b", low):
            folder = known_folder(v, default_dir)
            a = re.sub(rf"\s*\b(?:in|to|on|into)\s+(?:my\s+|the\s+)?{k}\b(\s+folder)?", "", a, flags=re.I)
            break
    name = suggested
    if a and not YES_ONLY.match(a):
        m = NAMED.search(a)
        cand = m.group(1) if m else a
        cand = re.sub(r"^\W*(yes|yeah|sure|ok(ay)?|save( it)?)[,\s]+", "", cand, flags=re.I).strip(" .!?")
        if cand and len(cand.split()) <= 8:
            name = slug(cand, suggested)
    return "save", folder / name


def unique(p: Path) -> Path:
    stem, ext, n = p.stem, p.suffix, 2
    q = p
    while q.exists():
        q = p.with_name(f"{stem} ({n}){ext}")
        n += 1
    return q


def allowed(folder: Path, default_dir: str) -> bool:
    """Saving is limited to your default folder, your LazyMonster folder and your own profile folders."""
    f = folder.resolve()
    roots = [Path(default_dir).resolve(), Path.home().resolve()]
    return any(str(f).lower().startswith(str(r).lower()) for r in roots)
