"""Runtime guards for UI control. Pure functions: tested on any OS.

Generic UI control can reach anything on screen, so the allowlist is enforced
here: where input may go, which keys may be pressed, what may be clicked, and
where code may be written."""
import re
from pathlib import PurePosixPath
from typing import List, Optional

# Keyboard / typing into these processes is refused: shells run commands,
# VS Code has an integrated terminal (code goes through code_write_file),
# and credential / security UIs must never be driven by a model.
BLOCKED_INPUT_PROCS = {
    "cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "openconsole.exe", "conhost.exe",
    "wsl.exe", "bash.exe", "wt.exe", "mintty.exe", "code.exe", "code - insiders.exe", "cursor.exe",
    "regedit.exe", "mmc.exe", "taskmgr.exe", "consent.exe", "credentialuibroker.exe", "lockapp.exe",
    "1password.exe", "bitwarden.exe", "keepass.exe", "keepassxc.exe", "lastpass.exe", "dashlane.exe",
    "systemsettings.exe", "control.exe", "msiexec.exe",
    # macOS and Linux
    "terminal", "iterm2", "code", "cursor", "keychain access", "1password", "system settings",
    "gnome-terminal-server", "konsole", "xterm", "alacritty", "kitty", "wezterm-gui", "tilix", "xfce4-terminal",
    "unknown",
}

RISKY_CLICK = re.compile(
    r"\b(delete|remove|erase|wipe|format|uninstall|send|submit|pay|buy|purchase|checkout|order|"
    r"transfer|withdraw|sign out|log ?out|reset|factory|empty (?:recycle )?bin|permanently|"
    r"end task|kill|allow|grant|trust|install|run as)\b", re.I)

_MODS = {"ctrl", "shift", "alt", "win"}
_KEYS = {"enter", "tab", "escape", "esc", "space", "backspace", "delete", "up", "down", "left", "right",
         "home", "end", "pageup", "pagedown", "f2", "f3", "f5", "f11"} | set("abcdefghijklmnopqrstuvwxyz0123456789")
# Combos that open a shell, run box, admin menu or close/shutdown flows.
_BANNED = {"win+r", "win+x", "win+l", "ctrl+`", "ctrl+shift+`", "ctrl+alt+t", "alt+f4", "ctrl+shift+esc",
           "ctrl+alt+delete", "win+s", "win+e", "ctrl+shift+enter", "shift+delete"}


class GuardError(PermissionError):
    pass


SENSITIVE_TITLE = re.compile(
    r"(password|passcode|passphrase|recovery|(?:backup|2fa|otp|verification|security)[ _-]?codes?|secret|"
    r"private.?key|api.?key|token|"
    r"\.env\b|\.pem\b|\.key\b|wallet|seed|mnemonic|bank|credential|\b2fa\b|\botp\b|vault|keychain|ssn|passport)", re.I)
NEW_DOC_TITLE = re.compile(
    r"^\*?\s*(untitled|document\s*\d*|new (tab|document|file|message|note)|book\s*\d+|presentation\s*\d+|blank)", re.I)
_APP_SUFFIX = re.compile(r"\s+[-\u2013\u2014|]\s+[^-\u2013\u2014|]+$")


def is_sensitive(title: str) -> bool:
    return bool(title) and bool(SENSITIVE_TITLE.search(title))


def redact_title(title: str) -> str:
    return "[sensitive window]" if is_sensitive(title) else title


def check_not_sensitive(title: str) -> None:
    if is_sensitive(title):
        raise GuardError("that window looks sensitive (passwords/keys/codes); the monster will not touch it. "
                         "Open a new document instead, or ask_user")


def owns(title: str, context: str) -> bool:
    """A window is ours to edit if it is a new/untitled document, or the user
    named it (a distinctive word of its title appears in what they said)."""
    if NEW_DOC_TITLE.search(title or ""):
        return True
    doc = _APP_SUFFIX.sub("", (title or "").lstrip("*").strip())
    words = {w for w in re.findall(r"[a-z0-9]{4,}", doc.lower()) if w not in {"txt", "docx", "file", "document"}}
    ctx = (context or "").lower()
    return any(w in ctx for w in words)


def check_type_target(title: str, context: str) -> None:
    check_not_sensitive(title)
    if not owns(title, context):
        raise GuardError(f"'{title}' is an existing document the user did not mention. Make a new one first "
                         "(press_keys ctrl+n), or ask_user before editing it")


_EDIT_KEYS = {"backspace", "delete", "enter", "space"}


def is_editing(parts) -> bool:
    """Keys that change document content (vs. navigate, open, save)."""
    mods = parts[:-1]
    key = parts[-1]
    if not mods:
        return key in _EDIT_KEYS or len(key) == 1
    return mods == ["ctrl"] and key in ("v", "x", "z", "y")


def check_input_target(process: Optional[str]) -> None:
    if not process:
        raise GuardError("no focused window; focus one with focus_window first")
    if process.lower() in BLOCKED_INPUT_PROCS:
        raise GuardError(f"typing or pressing keys into {process} is not allowed"
                         + ("; use code_write_file for code" if process.lower().startswith(("code", "cursor")) else ""))


def check_click(name: str, process: Optional[str]) -> None:
    if process and process.lower() in BLOCKED_INPUT_PROCS:
        raise GuardError(f"clicking inside {process} is not allowed")
    if RISKY_CLICK.search(name or ""):
        raise GuardError(f"'{name}' looks irreversible (delete/send/pay/install...); ask the user to click it")


def parse_keys(keys: str) -> List[str]:
    parts = [p.strip().lower() for p in re.split(r"\s*\+\s*", keys.strip()) if p.strip()]
    if not parts or len(parts) > 4:
        raise GuardError(f"bad key combo {keys!r}")
    norm = "+".join(parts)
    if norm in _BANNED:
        raise GuardError(f"{keys} is not allowed")
    *mods, key = parts
    if any(m not in _MODS for m in mods) or len(set(mods)) != len(mods):
        raise GuardError(f"bad modifiers in {keys!r}")
    if key not in _KEYS:
        raise GuardError(f"key {key!r} is not allowed")
    if "win" in mods and norm not in {"win+d", "win+up", "win+down", "win+left", "win+right"}:
        raise GuardError(f"{keys} is not allowed")
    return parts


SAFE_CODE_EXT = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss", ".json", ".md", ".txt",
                 ".toml", ".yaml", ".yml", ".ini", ".cfg", ".java", ".kt", ".c", ".h", ".cpp", ".hpp", ".cs",
                 ".go", ".rs", ".rb", ".php", ".swift", ".sql", ".csv", ".xml", ".svg", ".gitignore"}


def safe_rel_path(path: str) -> str:
    """Relative path inside a code project. No absolute paths, no '..', no
    executable-on-double-click file types."""
    p = path.replace("\\", "/").strip()
    if not p or p.startswith("/") or re.match(r"^[a-zA-Z]:", p):
        raise GuardError("path must be relative to the project")
    parts = PurePosixPath(p).parts
    if any(x in ("..", ".") for x in parts) or len(parts) > 6:
        raise GuardError("path may not contain '..' and must be at most 6 levels deep")
    if any(not re.fullmatch(r"[A-Za-z0-9 _.\-]{1,80}", x) for x in parts):
        raise GuardError("path segments may only use letters, digits, space, _ . -")
    name = parts[-1]
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if name.lower() != ".gitignore" and ext not in SAFE_CODE_EXT:
        raise GuardError(f"file type {ext or '(none)'} not allowed for code files")
    return "/".join(parts)


def safe_project(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9 _\-]+", "", name).strip()[:60]
    if not n:
        raise GuardError("bad project name")
    return n


_PKG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}(\[[A-Za-z0-9,._-]{1,40}\])?((==|>=|<=|~=)[A-Za-z0-9.*+!-]{1,30})?$")


def safe_packages(spec: str) -> list:
    """PyPI names only: no URLs, paths, flags or index options."""
    pkgs = spec.replace(",", " ").split()
    if not pkgs or len(pkgs) > 10:
        raise GuardError("give 1-10 package names")
    for p in pkgs:
        if p.startswith("-") or not _PKG.match(p):
            raise GuardError(f"'{p}' is not a plain package name")
    return pkgs
