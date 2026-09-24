"""Windows UI Automation (pywinauto). Called only from the worker thread."""
import difflib
import time

from ..guards import GuardError, check_click, check_input_target, check_not_sensitive, is_sensitive, redact_title


def _desktop():
    import sys
    import warnings
    sys.coinit_flags = 2                         # STA, matches the worker thread
    warnings.filterwarnings("ignore", message="Revert to STA COM threading mode")
    warnings.filterwarnings("ignore", message="Apply externally defined coinit_flags")
    from pywinauto import Desktop
    return Desktop(backend="uia")


def _proc_of(handle) -> str:
    try:
        import psutil
        import win32process
        _, pid = win32process.GetWindowThreadProcessId(handle)
        return psutil.Process(pid).name()
    except Exception:
        return ""


def foreground():
    import win32gui
    h = win32gui.GetForegroundWindow()
    return h, win32gui.GetWindowText(h), _proc_of(h)


def _windows():
    out = []
    for w in _desktop().windows():
        try:
            t = w.window_text()
            if t and w.is_visible():
                out.append((w, t, _proc_of(w.handle)))
        except Exception:
            continue
    return out


def _match(title: str):
    wins = _windows()
    if not wins:
        raise GuardError("no windows found")
    tl = title.lower()
    exact = [w for w in wins if tl in w[1].lower() or tl == w[2].lower().removesuffix(".exe")]
    if exact:
        return exact[0]
    best = difflib.get_close_matches(title, [w[1] for w in wins], n=1, cutoff=0.4)
    if not best:
        raise GuardError(f"no window matching {title!r}")
    return next(w for w in wins if w[1] == best[0])


def list_windows() -> str:
    return "\n".join(f"{redact_title(t)} | {p}" for _, t, p in _windows()[:40]) or "(no windows)"


def focus_window(title: str) -> str:
    w, t, p = _match(title)
    try:
        if w.is_minimized():
            w.restore()
        w.set_focus()
    except Exception:
        import win32gui
        win32gui.SetForegroundWindow(w.handle)
    time.sleep(0.25)
    return f"focused: {redact_title(t)} | {p}"


def read_window(title: str = "", limit: int = 180, budget_s: float = 2.5) -> str:
    if title:
        w, t, p = _match(title)
    else:
        h, t, p = foreground()
        w = _desktop().window(handle=h)
    if is_sensitive(t):
        return f"window: [sensitive window] | {p}\n(contents not read to protect secrets)"
    lines, t0 = [f"window: {t} | {p}"], time.monotonic()
    try:
        for c in w.descendants():
            if time.monotonic() - t0 > budget_s or len(lines) > limit:
                lines.append("…(truncated)")
                break
            try:
                name = c.window_text().strip()
                if not name:
                    continue
                ctype = c.element_info.control_type or "?"
                lines.append(f"{ctype}: {name[:120]}")
            except Exception:
                continue
    except Exception as e:
        lines.append(f"(could not read controls: {e})")
    return "\n".join(lines)


def click(name: str, window: str = "") -> str:
    if window:
        w, t, p = _match(window)
    else:
        h, t, p = foreground()
        w = _desktop().window(handle=h)
    check_not_sensitive(t)
    check_click(name, p)
    target, nl = None, name.lower()
    cands = []
    for c in w.descendants():
        try:
            txt = c.window_text().strip()
        except Exception:
            continue
        if not txt:
            continue
        if txt.lower() == nl:
            target = c
            break
        if nl in txt.lower():
            cands.append(c)
    target = target or (cands[0] if cands else None)
    if target is None:
        raise GuardError(f"no control named {name!r} in {t}; use read_window to see names")
    label = target.window_text()
    check_click(label, p)
    try:
        target.invoke()
    except Exception:
        target.click_input()
    time.sleep(0.3)
    return f"clicked {label!r} in {t}"


def handle_alive(h) -> bool:
    import win32gui
    try:
        return bool(h) and bool(win32gui.IsWindow(h))
    except Exception:
        return False


def focus_handle(h) -> None:
    try:
        w = _desktop().window(handle=h)
        if w.is_minimized():
            w.restore()
        w.set_focus()
    except Exception:
        import win32gui
        win32gui.SetForegroundWindow(h)
    time.sleep(0.2)


def match_handle(title: str):
    return _match(title)[0].handle


def read_document(h, raw: bool = False, limit: int = 4000, budget_s: float = 2.0):
    """The text content of a document window (Notepad, Word, editors, text boxes).
    Uses UI Automation TextPattern / ValuePattern; never reads sensitive windows."""
    import win32gui
    title = win32gui.GetWindowText(h) if h else ""
    if is_sensitive(title):
        return None if raw else "[sensitive window: contents not read]"
    w = _desktop().window(handle=h)
    best, t0 = "", time.monotonic()
    try:
        for c in w.descendants():
            if time.monotonic() - t0 > budget_s:
                break
            try:
                ct = c.element_info.control_type
            except Exception:
                continue
            if ct not in ("Document", "Edit"):
                continue
            text = ""
            try:
                text = c.iface_text.DocumentRange.GetText(200000)
            except Exception:
                try:
                    text = c.get_value()
                except Exception:
                    try:
                        text = c.window_text()
                    except Exception:
                        text = ""
            if text and len(text) > len(best):
                best = text
    except Exception:
        pass
    if raw:
        return best
    body = best if len(best) <= limit else best[:limit] + "\n…(truncated)"
    return f"document in {title}:\n{body}" if best else f"no readable text found in {title}"


def guard_focused_input() -> tuple:
    _, t, p = foreground()
    check_input_target(p)
    return t, p
