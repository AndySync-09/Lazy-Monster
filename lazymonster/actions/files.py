"""Sandboxed output folder: Documents\\LazyMonster. Never overwrites: picks a new name."""
import os
import re
from pathlib import Path


def documents_dir() -> Path:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:   # CSIDL_PERSONAL (OneDrive-aware)
            return Path(buf.value)
    return Path.home() / "Documents"


def out_dir() -> Path:
    d = documents_dir() / "LazyMonster"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_name(name: str, allowed_ext: tuple, default_ext: str) -> str:
    base = os.path.basename(name.replace("\\", "/")).strip()
    stem, ext = os.path.splitext(base)
    if ext.lower() not in allowed_ext:
        stem, ext = base, default_ext
    stem = re.sub(r"[^A-Za-z0-9 _.-]+", "", stem).strip(" .")[:80] or "untitled"
    return stem + ext.lower()


def unique_path(folder: Path, filename: str) -> Path:
    p = folder / filename
    stem, ext, n = p.stem, p.suffix, 2
    while p.exists():
        p = folder / f"{stem} ({n}){ext}"
        n += 1
    return p


def write_text(filename: str, text: str) -> Path:
    p = unique_path(out_dir(), safe_name(filename, (".txt", ".md"), ".txt"))
    p.write_text(text, encoding="utf-8")
    return p


OPENABLE = {".html", ".htm", ".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".csv", ".txt", ".md", ".png", ".jpg",
            ".jpeg", ".gif", ".svg", ".webp", ".mp3", ".mp4", ".json"}


def resolve_file(spec: str, default_dir: str = "") -> Path:
    """A full path, or a name / project/name of something the monster made. Only
    documents and media open this way; programs and scripts never do."""
    from ..guards import GuardError
    raw = spec.strip().strip('"')
    if raw.lower().startswith("file:///"):
        raw = raw[8:].replace("/", "\\\\") if os.name == "nt" else raw[7:]
    p = Path(raw)
    cands = [p] if p.is_absolute() else []
    if not p.is_absolute():
        roots = [out_dir() / "code", out_dir()] + ([Path(default_dir)] if default_dir else [])
        cands = [r / p for r in roots]
        for r in roots:
            if r.is_dir() and not (r / p).exists():
                cands += list(r.rglob(p.name))[:3]
    for c in cands:
        if c.is_file():
            if c.suffix.lower() not in OPENABLE:
                raise GuardError(f"{c.suffix or 'that'} files are not opened this way (documents and media only)")
            home = str(Path.home().resolve()).lower()
            okroots = [home] + ([str(Path(default_dir).resolve()).lower()] if default_dir else [])
            if not any(str(c.resolve()).lower().startswith(r) for r in okroots):
                raise GuardError("only files in your own folders or the default save folder")
            return c
    raise GuardError(f"could not find {spec}")
