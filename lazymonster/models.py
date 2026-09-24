"""Where on-device models live and how they are fetched."""
import os
from pathlib import Path


def models_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".cache")
    d = Path(base) / "lazymonster" / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def download(url: str, dest: Path, label: str = "") -> Path:
    """Resumable-enough download with a progress line; skips files already present."""
    import requests
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {label or dest.name}: {done * 100 // total}% of {total // 1_000_000} MB", end="", flush=True)
    print()
    tmp.replace(dest)
    return dest
