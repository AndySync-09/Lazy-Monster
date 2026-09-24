"""Allowlisted Windows actions. Only intents in intents.SCHEMA reach this file,
and nothing here builds a shell command from free text."""
import ctypes
import os
import subprocess
import time
import urllib.parse
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

VK_LETTERS = {c: ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
NAMED_VK = {"enter": 0x0D, "tab": 0x09, "escape": 0x1B, "esc": 0x1B, "space": 0x20, "backspace": 0x08,
            "delete": 0x2E, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23,
            "pageup": 0x21, "pagedown": 0x22, "f2": 0x71, "f3": 0x72, "f5": 0x74, "f11": 0x7A,
            "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
VK = dict(VOLUME_MUTE=0xAD, VOLUME_DOWN=0xAE, VOLUME_UP=0xAF, MEDIA_NEXT=0xB0, MEDIA_PREV=0xB1,
          MEDIA_PLAY_PAUSE=0xB3, LWIN=0x5B, CONTROL=0x11, MENU=0x12, SHIFT=0x10, TAB=0x09,
          D=0x44, T=0x54, W=0x57, SNAPSHOT=0x2C)
EXTENDED = {0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB3, 0x5B, 0x2C, 0x2E, 0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22}
KEYUP, EXT_FLAG, UNICODE_FLAG = 0x0002, 0x0001, 0x0004
NO_WINDOW = 0x08000000

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _key(vk: int, up: bool = False) -> None:
    flags = (KEYUP if up else 0) | (EXT_FLAG if vk in EXTENDED else 0)
    inp = INPUT(type=1, u=_U(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def chord(*vks: int) -> None:
    for v in vks:
        _key(v)
    for v in reversed(vks):
        _key(v, up=True)


def type_unicode(text: str) -> None:
    for ch in text:
        if True:
            cp = ord(ch)
            units = [cp] if cp < 0x10000 else [0xD800 + ((cp - 0x10000) >> 10), 0xDC00 + ((cp - 0x10000) & 0x3FF)]
            for u in units:
                for up in (0, KEYUP):
                    inp = INPUT(type=1, u=_U(ki=KEYBDINPUT(wVk=0, wScan=u, dwFlags=UNICODE_FLAG | up, time=0, dwExtraInfo=0)))
                    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _clip_get():
    import win32clipboard as cb
    cb.OpenClipboard()
    try:
        return cb.GetClipboardData(cb.CF_UNICODETEXT) if cb.IsClipboardFormatAvailable(cb.CF_UNICODETEXT) else None
    finally:
        cb.CloseClipboard()


def _clip_set(text: str) -> None:
    import win32clipboard as cb
    for _ in range(5):                               # the clipboard can be briefly locked by other apps
        try:
            cb.OpenClipboard()
            try:
                cb.EmptyClipboard()
                cb.SetClipboardData(cb.CF_UNICODETEXT, text)
                return
            finally:
                cb.CloseClipboard()
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("clipboard busy")


def paste_text(text: str, line_delay: float = 0.04) -> None:
    """Paste line by line (Enter between lines): exact, fast and still visibly live.
    Restores the user's text clipboard afterwards."""
    from ..textops import paste_lines
    saved = None
    try:
        saved = _clip_get()
    except Exception:
        pass
    try:
        lines = paste_lines(text)
        for i, line in enumerate(lines):
            if line:
                _clip_set(line)
                chord(VK["CONTROL"], 0x56)           # ctrl+v
                time.sleep(line_delay)
            if i < len(lines) - 1:
                chord(0x0D)                          # enter
                time.sleep(0.01)
    finally:
        time.sleep(0.1)
        if saved is not None:
            try:
                _clip_set(saved)
            except Exception:
                pass


def _endpoint_volume():
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass
    from pycaw.pycaw import AudioUtilities
    dev = AudioUtilities.GetSpeakers()
    vol = getattr(dev, "EndpointVolume", None)          # newer pycaw
    if vol is not None:
        return vol
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))


def _run(args) -> None:
    subprocess.Popen(args, creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class WindowsExecutor:
    def __init__(self, apps, writer=None):
        self.apps, self.writer = apps, writer
        self.word = None
        self.context = ""                 # what the user said this session (set by the agent)
        self.target = None                # window handle the monster is working in
        self.owned = []                   # what the monster opened this session, for "close everything"
        self.default_save_dir = "C:\\temp"

    def run(self, intent):
        """Returns (ok, message, output). output feeds $N references in later steps."""
        fn = getattr(self, "_" + intent.name, None)
        if fn is None:
            return False, f"no handler for {intent.name}", None
        try:
            res = fn(**intent.args)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", None
        return res if len(res) == 3 else (res[0], res[1], res[1])

    # ---- agent tools: see and drive the desktop ---------------------------
    def _list_windows(self):
        from . import uia
        return True, uia.list_windows()

    def _focus_window(self, title):
        from . import uia
        msg = uia.focus_window(title)
        self.target = uia.foreground()[0]
        return True, msg

    def _ensure_target(self):
        """Type into the window the monster opened/focused, not whatever has focus now."""
        from . import uia
        if self.target and uia.foreground()[0] != self.target and uia.handle_alive(self.target):
            uia.focus_handle(self.target)

    def _read_text(self, title=""):
        from . import uia
        h = uia.match_handle(title) if title else (self.target or uia.foreground()[0])
        return True, uia.read_document(h)

    def _verify_in(self, text) -> str:
        from . import uia
        from ..textops import verify
        time.sleep(0.2)
        doc = uia.read_document(self.target or uia.foreground()[0], raw=True)
        if doc is None:
            return "could not read the document back to verify"
        return verify(text, doc)[1]

    def _write_in_app(self, app, text):
        from . import uia
        from ..guards import NEW_DOC_TITLE, check_type_target
        ok, msg = self._open_app(app)
        if not ok:
            return False, msg
        _, title, _ = uia.foreground()
        if not NEW_DOC_TITLE.search(title or ""):
            chord(VK["CONTROL"], VK_LETTERS["N"])
            time.sleep(0.8)
        self.target, title, proc = uia.foreground()
        check_type_target(title, "")                # must be a fresh document now
        uia.guard_focused_input()
        paste_text(text)
        self._own(self.target, app, proc)
        self._retitle(self.target)
        return True, f"wrote {len(text)} chars into {title}; " + self._verify_in(text)

    def _read_window(self, title=""):
        from . import uia
        return True, uia.read_window(title)

    def _click(self, name, window=""):
        from . import uia
        return True, uia.click(name, window)

    def _press_keys(self, keys):
        from . import uia
        from ..guards import check_not_sensitive, check_type_target, is_editing, parse_keys
        parts = parse_keys(keys)
        self._ensure_target()
        title, _ = uia.guard_focused_input()
        check_not_sensitive(title)
        if is_editing(parts):
            check_type_target(title, self.context)
        vks = [NAMED_VK[p] if p in NAMED_VK else ord(p.upper()) for p in parts]
        chord(*vks)
        time.sleep(0.15)
        if parts[-1] == "n" and parts[:-1] == ["ctrl"]:
            self.target = uia.foreground()[0]       # a new document/tab is the new target
        return True, f"pressed {keys}"

    def _code(self):
        if getattr(self, "code", None) is None:
            from .code import CodeWorkspace
            self.code = CodeWorkspace()
        return self.code

    def _code_open(self, project):
        msg = self._code().open(project)
        from . import uia
        h, _, proc = uia.foreground()
        if "code" in (proc or "").lower():
            self._own(h, "VS Code", proc)
        return True, msg

    def _code_write_file(self, project, path, content):
        return True, self._code().write(project, path, content)

    def _code_run(self, project, path):
        res = self._code().run(project, path)
        p = getattr(self._code(), "last_proc", None)
        if p is not None and p.poll() is None:
            self.owned.append({"kind": "proc", "proc": p, "label": f"{path} from {project}", "dirty": False})
        return res

    def _code_install(self, project, packages):
        return self._code().install(project, packages)

    def _finish(self, summary="", next=""):
        return True, summary or "done"

    def _word(self):
        if self.word is None:
            from .office import WordSession
            self.word = WordSession()
        return self.word

    def _word_new_document(self):
        msg = self._word().new_document()
        self.owned.append({"kind": "word", "doc": self._word().doc, "label": "the Word document", "dirty": False})
        return True, msg

    def _word_insert_text(self, text):
        return True, self._word().insert_text(text)

    def _word_save(self, filename):
        return True, self._word().save(filename)

    def _file_write_text(self, filename, text):
        from .files import write_text
        return True, f"saved {write_text(filename, text)}"

    def _open_url(self, url):
        if not url.lower().startswith(("http://", "https://")):
            return False, "only http(s) URLs are allowed"
        os.startfile(url)
        return True, f"opened {url}"

    # ---- audio ------------------------------------------------------------
    def _volume_set(self, level):
        try:
            _endpoint_volume().SetMasterVolumeLevelScalar(level / 100.0, None)
            return True, f"volume {level}"
        except Exception:
            for _ in range(50):                      # key fallback: 2% per press
                chord(VK["VOLUME_DOWN"])
            for _ in range(round(level / 2)):
                chord(VK["VOLUME_UP"])
            return True, f"volume ~{level} (keys)"

    def _volume_step(self, step, sign):
        try:
            v = _endpoint_volume()
            cur = v.GetMasterVolumeLevelScalar()
            v.SetMasterVolumeLevelScalar(min(1.0, max(0.0, cur + sign * step / 100.0)), None)
            return True, f"volume {'+' if sign > 0 else '-'}{step}"
        except Exception:
            for _ in range(max(1, step // 2)):
                chord(VK["VOLUME_UP" if sign > 0 else "VOLUME_DOWN"])
            return True, "volume step (keys)"

    def _volume_up(self, step=10):
        return self._volume_step(step, +1)

    def _volume_down(self, step=10):
        return self._volume_step(step, -1)

    def _mute(self):
        try:
            _endpoint_volume().SetMute(1, None)
        except Exception:
            chord(VK["VOLUME_MUTE"])
        return True, "muted"

    def _unmute(self):
        try:
            _endpoint_volume().SetMute(0, None)
        except Exception:
            chord(VK["VOLUME_MUTE"])
        return True, "unmuted"

    def _media_play_pause(self):
        chord(VK["MEDIA_PLAY_PAUSE"]); return True, "play/pause"

    def _media_next(self):
        chord(VK["MEDIA_NEXT"]); return True, "next"

    def _media_prev(self):
        chord(VK["MEDIA_PREV"]); return True, "previous"

    # ---- windows & keys -----------------------------------------------------
    def _lock(self):
        user32.LockWorkStation(); return True, "locked"

    def _screenshot(self):
        chord(VK["LWIN"], VK["SNAPSHOT"]); return True, "saved to Pictures\\Screenshots"

    def _new_tab(self):
        chord(VK["CONTROL"], VK["T"]); return True, "new tab"

    def _close_tab(self):
        chord(VK["CONTROL"], VK["W"]); return True, "closed tab"

    def _minimize(self):
        user32.ShowWindow(user32.GetForegroundWindow(), 6); return True, "minimized"

    def _maximize(self):
        user32.ShowWindow(user32.GetForegroundWindow(), 3); return True, "maximized"

    def _show_desktop(self):
        chord(VK["LWIN"], VK["D"]); return True, "desktop"

    def _switch_window(self):
        chord(VK["MENU"], VK["TAB"]); return True, "switched"

    def _brightness_set(self, level):
        ps = ("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods) | "
              f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1;Brightness={int(level)}}}")
        _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])
        return True, f"brightness {level} (built-in displays only)"

    def _type_text(self, text):
        from . import uia
        from ..guards import check_type_target
        self._ensure_target()
        time.sleep(0.15)                            # let focus settle
        title, _ = uia.guard_focused_input()
        check_type_target(title, self.context)
        self.target = uia.foreground()[0]
        paste_text(text)
        self._retitle(self.target)
        return True, f"wrote {len(text)} chars into {title}; " + self._verify_in(text)

    # ---- apps, web, settings ----------------------------------------------
    def _open_target(self, target):
        try:
            os.startfile(target)
        except OSError:
            _run(["cmd", "/c", "start", "", target])

    def _open_app(self, app):
        key = self.apps.apps.get(app) and app or self.apps.resolve(app)
        entry = self.apps.apps.get(key) if key else None
        if not entry:
            return False, f"unknown app {app}; known apps include: {', '.join(sorted(self.apps.apps)[:30])}"
        self._open_target(entry["open"])
        time.sleep(1.5)                             # give it a moment to appear
        try:
            from . import uia
            from ..guards import NEW_DOC_TITLE, redact_title
            self.target, title, proc = uia.foreground()
            self._own(self.target, key, proc)
            note = "" if NEW_DOC_TITLE.search(title or "") else " (an existing document; press ctrl+n for a new one before typing)"
            return True, f"opened {key}; focused window is now: {redact_title(title)} | {proc}{note}"
        except Exception:
            return True, f"opened {key}"

    def _close_app(self, app):
        key = app if app in self.apps.apps else self.apps.resolve(app)
        entry = self.apps.apps.get(key) if key else None
        proc = entry and entry.get("process")
        if not proc:
            return False, f"don't know the process for {app}; add it to config"
        _run(["taskkill", "/IM", proc])            # graceful: apps may ask to save
        return True, f"asked {app} to close"

    def _open_settings(self, page=""):
        os.startfile("ms-settings:" + page); return True, f"settings {page or 'home'}"

    def _search_web(self, query):
        os.startfile("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
        return True, "searched"

    # ---- power (engine asks for confirmation first) ---------------------
    def _sleep(self):
        _run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]); return True, "sleeping"

    def _shutdown(self):
        _run(["shutdown", "/s", "/t", "5"]); return True, "shutting down in 5s (shutdown /a to abort)"

    def _restart(self):
        _run(["shutdown", "/r", "/t", "5"]); return True, "restarting in 5s (shutdown /a to abort)"

    # ---- ownership: close what the monster opened, and only that -------------------
    def _own(self, hwnd, app, proc=""):
        if not hwnd or any(o.get("hwnd") == hwnd for o in self.owned):
            return
        import win32gui
        self.owned.append({"kind": "window", "hwnd": hwnd, "app": str(app), "proc": (proc or "").lower(),
                           "title": win32gui.GetWindowText(hwnd), "label": str(app).title()})

    def _retitle(self, hwnd):
        """Remember the tab title right after writing: that is how 'our' Notepad tab is recognised later."""
        import win32gui
        for o in self.owned:
            if o.get("hwnd") == hwnd:
                o["title"] = win32gui.GetWindowText(hwnd)

    def owned_items(self) -> list:
        """What is still open, with unsaved state and a suggested file name."""
        import win32gui
        from ..savepaths import slug
        from . import uia
        live = []
        for o in self.owned:
            if o["kind"] == "window":
                if not uia.handle_alive(o["hwnd"]):
                    continue
                title = win32gui.GetWindowText(o["hwnd"])
                o["dirty"] = title.startswith("*")
                base = title.lstrip("*").rsplit(" - ", 1)[0].strip()
                if o["dirty"] and base.lower().startswith("untitled"):
                    text = uia.read_document(o["hwnd"], raw=True) or ""
                    base = " ".join(text.split()[:5]) or "note"
                ext = ".docx" if "winword" in o["proc"] else ".txt"
                o["suggest"] = slug(base, "note") + ext
                o["label"] = f"{o['app'].title()} ({title.lstrip('*').rsplit(' - ', 1)[0].strip()[:40]})"
            elif o["kind"] == "word":
                try:
                    o["dirty"] = not bool(o["doc"].Saved)
                    words = " ".join(str(o["doc"].Content.Text).split()[:5])
                    o["suggest"] = slug(words, "document") + ".docx"
                except Exception:
                    continue                                   # the user already closed it
            elif o["kind"] == "proc":
                if o["proc"].poll() is not None:
                    continue
            live.append(o)
        self.owned = live
        return live

    def save_item(self, o, path) -> str:
        from pathlib import Path
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if o["kind"] == "word":
            if path.suffix.lower() not in (".docx", ".doc"):
                path = path.with_suffix(".docx")
            o["doc"].SaveAs2(str(path), 16)
            return str(path)
        from . import uia
        text = uia.read_document(o["hwnd"], raw=True)
        if text is None:
            raise RuntimeError("could not read the window's text")
        if not path.suffix:
            path = path.with_suffix(".txt")
        path.write_text(text, encoding="utf-8")
        return str(path)

    def close_item(self, o, discard_prompt: bool = True) -> str:
        """Close one thing the monster opened. Notepad: only our tab (Ctrl+W on it),
        never the user's other tabs. If the app asks to save, we already saved (or you said no)."""
        import win32con
        import win32gui
        from . import uia
        if o["kind"] == "proc":
            o["proc"].terminate()
            return f"stopped {o['label']}"
        if o["kind"] == "word":
            o["doc"].Close(0)
            try:
                if self._word().word.Documents.Count == 0:
                    self._word().word.Quit()
            except Exception:
                pass
            return "closed the Word document"
        h = o["hwnd"]
        if "notepad" in o["proc"]:
            uia.focus_handle(h)
            now = win32gui.GetWindowText(h).lstrip("*")
            if now != o["title"].lstrip("*"):
                return f"left {o['label']} open (a different tab is showing; I only close tabs I wrote in)"
            chord(VK["CONTROL"], VK["W"])
        else:
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        time.sleep(0.8)
        if discard_prompt:
            try:
                uia.click("Don't save")
            except Exception:
                pass
        return f"closed {o['label']}"

    # ---- documents: open, PDF, decks ------------------------------------------------
    APP_EXE = {"chrome": "chrome.exe", "google chrome": "chrome.exe", "edge": "msedge.exe", "microsoft edge": "msedge.exe",
               "word": "WINWORD.EXE", "powerpoint": "POWERPNT.EXE", "excel": "EXCEL.EXE", "notepad": "notepad.exe"}

    @staticmethod
    def _app_path(exe: str):
        import shutil
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                    return winreg.QueryValueEx(k, "")[0]
            except OSError:
                continue
        return shutil.which(exe)

    def _open_file(self, path, app=""):
        import subprocess
        from .files import resolve_file
        f = resolve_file(path, self.default_save_dir)
        if app:
            exe = self._app_path(self.APP_EXE.get(app.lower().strip(), app))
            if not exe:
                return False, f"could not find {app}"
            subprocess.Popen([exe, str(f)])
        else:
            os.startfile(str(f))
        time.sleep(1.5)
        from . import uia
        h, title, proc = uia.foreground()
        self._own(h, app or f.suffix.lstrip(".").upper(), proc)
        return True, f"opened {f}" + (f" in {app}" if app else "") + f"; focused window: {title}"

    def _export_pdf(self):
        from pathlib import Path
        from .files import out_dir
        doc = self._word()._current()
        base = Path(doc.FullName) if doc.Path else out_dir() / "document.docx"
        pdf = base.with_suffix(".pdf")
        doc.ExportAsFixedFormat(str(pdf), 17)                  # wdExportFormatPDF
        os.startfile(str(pdf))
        return True, f"saved and opened {pdf}"

    def _make_presentation(self, filename, outline):
        from ..office_docs import build_pptx
        from .files import out_dir, safe_name, unique_path
        p = unique_path(out_dir(), safe_name(filename, (".pptx",), ".pptx"))
        build_pptx(filename, outline, p)
        os.startfile(str(p))
        time.sleep(2.0)
        from . import uia
        h, title, proc = uia.foreground()
        self._own(h, "PowerPoint", proc)
        return True, f"built and opened {p}"

    def _draft_email(self, subject="", body="", to=""):
        """A draft in your mail app, filled in. You press Send; the monster never does."""
        from urllib.parse import quote
        url = f"mailto:{quote(to or '', safe='@,')}?subject={quote(subject or '')}&body={quote((body or '')[:1800])}"
        os.startfile(url)
        return True, f"opened an email draft{' to ' + to if to else ''} titled {subject!r}; the user reviews and sends it"

    # ---- looking at the screen (only when asked) ------------------------------------------
    def capture_screen(self) -> dict:
        """The window in front of you: its title, its text, and a screenshot of just that
        window (kept in memory for this one question, never saved). Private windows are refused."""
        import base64
        import io
        import win32con
        import win32gui
        from ..guards import is_sensitive
        from . import uia
        hwnd = win32gui.GetForegroundWindow()
        # if you clicked the monster's own window, look at the one behind it
        for _ in range(30):
            t = win32gui.GetWindowText(hwnd)
            if hwnd and win32gui.IsWindowVisible(hwnd) and t and t != "Lazy-Monster" and not win32gui.IsIconic(hwnd):
                break
            hwnd = win32gui.GetWindow(hwnd, win32con.GW_HWNDNEXT)
        title = win32gui.GetWindowText(hwnd)
        if is_sensitive(title):
            return {"blocked": True, "title": "[private window]"}
        proc = ""
        try:
            import psutil
            import win32process
            proc = psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1]).name()
        except Exception:
            pass
        text = ""
        try:
            text = uia.read_document(hwnd, raw=True) or ""
        except Exception:
            pass
        img = None
        try:
            from PIL import ImageGrab
            l, t_, r, b = win32gui.GetWindowRect(hwnd)
            shot = ImageGrab.grab(bbox=(l, t_, r, b), all_screens=True).convert("RGB")
            shot.thumbnail((1400, 1400))
            buf = io.BytesIO()
            shot.save(buf, "JPEG", quality=80)
            img = base64.b64encode(buf.getvalue()).decode()
        except Exception:
            img = None
        return {"title": title, "app": proc or "", "text": text[:8000], "image": img}
