"""macOS helpers: AppleScript and the Accessibility API. Requires the one-time
Accessibility and Automation permissions (the installer walks you through them)."""
import json
import subprocess
import time


def osa(script: str, timeout: float = 8.0) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "AppleScript failed").strip()[:200])
    return r.stdout.strip()


def q(s: str) -> str:
    return json.dumps(s)                                    # AppleScript string literal


def front() -> tuple:
    """(app process name, front window title)."""
    out = osa('tell application "System Events" to set p to first application process whose frontmost is true\n'
              'set n to name of p\n'
              'try\n set t to name of front window of p\non error\n set t to ""\nend try\n'
              'return n & "\\n" & t')
    name, _, title = out.partition("\n")
    return name, title


def app_running(app: str) -> bool:
    try:
        return osa(f"application {q(app)} is running") == "true"
    except Exception:
        return False


def list_windows() -> list:
    out = osa('set out to ""\ntell application "System Events"\n'
              ' repeat with p in (application processes whose visible is true)\n'
              '  repeat with w in windows of p\n'
              '   set out to out & (name of w as text) & " | " & (name of p) & linefeed\n'
              '  end repeat\n end repeat\nend tell\nreturn out')
    return [l for l in out.splitlines() if l.strip()]


def focus(title: str) -> str:
    return osa('tell application "System Events"\n'
               ' repeat with p in (application processes whose visible is true)\n'
               '  repeat with w in windows of p\n'
               f'   if (name of w as text) contains {q(title)} then\n'
               '    set frontmost of p to true\n    perform action "AXRaise" of w\n'
               '    return (name of w as text) & " | " & (name of p)\n'
               '   end if\n  end repeat\n end repeat\nend tell\nreturn ""')


def click(name: str) -> str:
    return osa('tell application "System Events" to tell (first application process whose frontmost is true)\n'
               f' set targets to (every button of front window whose name is {q(name)})\n'
               ' if targets is {} then set targets to (every UI element of front window whose name is ' + q(name) + ')\n'
               ' if targets is {} then return ""\n click item 1 of targets\n return "clicked"\nend tell')


def keystroke_paste(text: str) -> None:
    """Paste through the clipboard (exact), restoring what you had copied."""
    saved = subprocess.run(["pbpaste"], capture_output=True).stdout
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        osa('tell application "System Events" to keystroke "v" using command down')
        time.sleep(0.25)
    finally:
        subprocess.run(["pbcopy"], input=saved)


def focused_text() -> str:
    """Text of the focused text area, via the Accessibility API."""
    try:
        from ApplicationServices import (AXUIElementCopyAttributeValue, AXUIElementCreateSystemWide,
                                         kAXFocusedUIElementAttribute, kAXValueAttribute)
        sysw = AXUIElementCreateSystemWide()
        err, el = AXUIElementCopyAttributeValue(sysw, kAXFocusedUIElementAttribute, None)
        if err or el is None:
            return ""
        err, val = AXUIElementCopyAttributeValue(el, kAXValueAttribute, None)
        return str(val) if not err and val is not None else ""
    except Exception:
        return ""


def trusted() -> bool:
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def word_save_pdf(path: str) -> None:
    osa('tell application "Microsoft Word"\n'
        f' save as active document file name {q(path)} file format format PDF\nend tell', timeout=60)


def quit_app(app: str) -> None:
    osa(f"tell application {q(app)} to quit", timeout=20)          # the app asks about unsaved work itself
