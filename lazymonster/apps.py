"""App resolver: config aliases + Windows Start Menu shortcuts (fuzzy)."""
import difflib
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_ALIASES: Dict[str, dict] = {
    "chrome":     {"open": "chrome",   "process": "chrome.exe",  "say": ["chrome", "google chrome", "browser"]},
    "edge":       {"open": "msedge",   "process": "msedge.exe",  "say": ["edge", "microsoft edge"]},
    "firefox":    {"open": "firefox",  "process": "firefox.exe", "say": ["firefox"]},
    "notepad":    {"open": "notepad",  "process": "notepad.exe", "say": ["notepad"]},
    "calculator": {"open": "calc",     "process": "CalculatorApp.exe", "say": ["calculator", "calc"]},
    "explorer":   {"open": "explorer", "process": None, "say": ["explorer", "file explorer", "files", "my files"]},
    "terminal":   {"open": "wt",       "process": "WindowsTerminal.exe", "say": ["terminal", "windows terminal", "command prompt", "powershell"]},
    "vscode":     {"open": "code",     "process": "Code.exe", "say": ["vs code", "vscode", "visual studio code", "code"]},
    "word":       {"open": "winword",  "process": "WINWORD.EXE", "say": ["word", "microsoft word", "ms word"]},
    "excel":      {"open": "excel",    "process": "EXCEL.EXE", "say": ["excel", "microsoft excel"]},
    "powerpoint": {"open": "powerpnt", "process": "POWERPNT.EXE", "say": ["powerpoint", "power point", "microsoft powerpoint"]},
    "outlook":    {"open": "outlook",  "process": "olk.exe", "say": ["outlook", "mail", "email"]},
    "teams":      {"open": "ms-teams:", "process": "ms-teams.exe", "say": ["teams", "microsoft teams"]},
    "spotify":    {"open": "spotify:", "process": "Spotify.exe", "say": ["spotify", "music"]},
    "settings":   {"open": "ms-settings:", "process": "SystemSettings.exe", "say": ["settings", "windows settings"]},
    "task manager": {"open": "taskmgr", "process": "Taskmgr.exe", "say": ["task manager"]},
    "youtube":    {"open": "https://www.youtube.com", "process": None, "say": ["youtube"]},
    "gmail":      {"open": "https://mail.google.com", "process": None, "say": ["gmail"]},
    "github":     {"open": "https://github.com", "process": None, "say": ["github", "git hub"]},
    "claude":     {"open": "https://claude.ai", "process": None, "say": ["claude"]},
}

_STRIP = re.compile(r"^(?:the |my |app |application )+|(?: app| application| please| for me)+$")


def _norm(s: str) -> str:
    return _STRIP.sub("", re.sub(r"[^a-z0-9 ]+", " ", s.lower())).strip()


class AppIndex:
    def __init__(self, aliases: Optional[Dict[str, dict]] = None, scan_start_menu: bool = True):
        self.apps: Dict[str, dict] = {k: dict(v) for k, v in (aliases or DEFAULT_ALIASES).items()}
        if scan_start_menu and os.name == "nt":
            self._scan_start_menu()
        self.spoken: Dict[str, str] = {}
        for key, v in self.apps.items():
            for s in v.get("say", []) + [key]:
                self.spoken.setdefault(_norm(s), key)

    def _scan_start_menu(self) -> None:
        roots = [Path(os.environ.get("ProgramData", r"C:\ProgramData")),
                 Path(os.environ.get("APPDATA", ""))]
        for r in roots:
            base = r / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            if not base.is_dir():
                continue
            for lnk in base.rglob("*.lnk"):
                name = _norm(lnk.stem)
                if not name or "uninstall" in name or len(name) > 40:
                    continue
                key = name
                if key not in self.apps:
                    self.apps[key] = {"open": str(lnk), "process": None, "say": [name]}

    def resolve(self, spoken: str) -> Optional[str]:
        s = _norm(spoken)
        if not s:
            return None
        if s in self.spoken:
            return self.spoken[s]
        m = difflib.get_close_matches(s, list(self.spoken), n=1, cutoff=0.82)
        return self.spoken[m[0]] if m else None

    def keyterms(self, limit: int = 120) -> List[str]:
        """Proper nouns to bias the speech model towards."""
        terms = ["Monster", "Lazy Monster"]
        for key, v in self.apps.items():
            for s in [key] + v.get("say", []):
                t = s.title() if s.islower() else s
                if "," not in t and t not in terms:
                    terms.append(t)
        return terms[:limit]
