"""macOS and Linux executor (first cut). Opening apps, URLs, files, code, volume,
media, locking and typing work; window reading/clicking and Office automation
are Windows-only for now (planned: macOS Accessibility API, Linux AT-SPI).
Unsupported tools return a clear error so the agent can adapt or ask."""
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import webbrowser

MAC = sys.platform == "darwin"
MAC_NAMES = {"chrome": "Google Chrome", "google chrome": "Google Chrome", "edge": "Microsoft Edge",
             "microsoft edge": "Microsoft Edge", "word": "Microsoft Word", "powerpoint": "Microsoft PowerPoint",
             "excel": "Microsoft Excel", "vscode": "Visual Studio Code", "vs code": "Visual Studio Code",
             "notepad": "TextEdit", "textedit": "TextEdit", "explorer": "Finder", "finder": "Finder",
             "terminal": "Terminal", "calculator": "Calculator", "spotify": "Spotify", "safari": "Safari",
             "settings": "System Settings", "outlook": "Microsoft Outlook", "teams": "Microsoft Teams"}
WAYLAND = os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
_KEYS_MAC = {"enter": 36, "tab": 48, "escape": 53, "esc": 53, "space": 49, "backspace": 51, "delete": 117,
             "up": 126, "down": 125, "left": 123, "right": 124, "home": 115, "end": 119}


def _run(args, check=False):
    return subprocess.run(args, capture_output=True, text=True, timeout=10, check=check)


def _osa(script: str) -> str:
    return _run(["osascript", "-e", script]).stdout.strip()


class PosixExecutor:
    def __init__(self, apps, writer=None):
        self.apps, self.context, self.target = apps, "", None
        self.code = None
        self.owned = []                 # apps it launched (it quits only those) and programs it ran
        self.doc_parts = []             # Word-style document being written (saved as .docx)
        self.default_save_dir = ""

    def run(self, intent):
        fn = getattr(self, "_" + intent.name, None)
        if fn is None:
            return False, f"{intent.name} is not supported on {'macOS' if MAC else 'Linux'} yet", None
        try:
            res = fn(**intent.args)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", None
        return res if len(res) == 3 else (res[0], res[1], res[1])

    # ---- focus and input -------------------------------------------------------
    def _front(self):
        if MAC:
            from . import mac
            name, title = mac.front()
            self._title = title
            return name
        if shutil.which("xdotool") and not WAYLAND:
            pid = _run(["xdotool", "getactivewindow", "getwindowpid"]).stdout.strip()
            if pid.isdigit():
                import psutil
                return psutil.Process(int(pid)).name()
        return ""

    def _guard_input(self):
        from ..guards import check_input_target
        name = self._front()
        check_input_target(name or "unknown")
        return name

    def _type_text(self, text):
        from ..guards import check_not_sensitive, check_type_target
        app = self._guard_input()
        if MAC:
            from . import mac
            from ..textops import verify
            title = getattr(self, "_title", "") or "Untitled"
            check_not_sensitive(title)
            check_type_target(title, self.context)
            mac.keystroke_paste(text)
            doc = mac.focused_text()
            note = verify(text, doc)[1] if doc else "could not read it back to verify"
            return True, f"wrote {len(text)} chars into {title} ({app}); {note}"
        check_type_target("Untitled", self.context)          # window titles are not readable here yet
        if shutil.which("xdotool") and not WAYLAND:
            _run(["xdotool", "type", "--delay", "8", "--", text])
        else:
            return False, "typing needs xdotool on X11 (Wayland blocks simulated input)"
        return True, f"typed {len(text)} chars into {app} (not verified on this platform)"

    def _press_keys(self, keys):
        from ..guards import parse_keys
        parts = parse_keys(keys)
        self._guard_input()
        *mods, key = parts
        if MAC:
            using = ", ".join({"ctrl": "command down", "shift": "shift down", "alt": "option down"}[m]
                              for m in mods if m != "win")
            action = f"key code {_KEYS_MAC[key]}" if key in _KEYS_MAC else f"keystroke {json_str(key)}"
            _osa(f'tell application "System Events" to {action}' + (f" using {{{using}}}" if using else ""))
        elif shutil.which("xdotool") and not WAYLAND:
            xk = {"enter": "Return", "esc": "Escape", "escape": "Escape", "backspace": "BackSpace",
                  "pageup": "Prior", "pagedown": "Next", "win": "super"}
            _run(["xdotool", "key", "+".join(xk.get(p, p) for p in parts)])
        else:
            return False, "key presses need xdotool on X11"
        return True, f"pressed {keys}"

    # ---- apps, web, files, code -------------------------------------------------------
    def _open_app(self, app):
        key = app if app in self.apps.apps else (self.apps.resolve(app) or app)
        name = MAC_NAMES.get(key.lower(), key.title()) if MAC else key
        if MAC:
            from . import mac
            was_running = mac.app_running(name)
            r = _run(["open", "-a", name])
            ok = r.returncode == 0
            if ok and not was_running and not any(o.get("app") == name for o in self.owned):
                self.owned.append({"kind": "app", "app": name, "label": name, "dirty": False})
        else:
            exe = shutil.which(key) or shutil.which(key.replace(" ", "-"))
            ok = bool(exe)
            if exe:
                subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1.2)
        return (True, f"opened {name}") if ok else (False, f"could not open {app}")

    def _write_in_app(self, app, text):
        ok, msg = self._open_app(app or ("TextEdit" if MAC else "gedit"))
        if not ok:
            return False, msg
        if MAC:
            time.sleep(0.8)
            _osa('tell application "System Events" to keystroke "n" using {command down}')   # always a new document
            time.sleep(0.8)
        return self._type_text(text)

    def _open_url(self, url):
        if not url.lower().startswith(("http://", "https://")):
            return False, "only http(s) URLs are allowed"
        webbrowser.open(url)
        return True, f"opened {url}"

    def _search_web(self, query):
        webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
        return True, "searched"

    def _file_write_text(self, filename, text):
        from .files import write_text
        return True, f"saved {write_text(filename, text)}"

    def _code_open(self, project):
        from .code import CodeWorkspace
        self.code = self.code or CodeWorkspace()
        return True, self.code.open(project)

    def _code_write_file(self, project, path, content):
        from .code import CodeWorkspace
        self.code = self.code or CodeWorkspace()
        return True, self.code.write(project, path, content)

    def _code_run(self, project, path):
        from .code import CodeWorkspace
        self.code = self.code or CodeWorkspace()
        res = self.code.run(project, path)
        p = getattr(self.code, "last_proc", None)
        if p is not None and p.poll() is None:
            self.owned.append({"kind": "proc", "proc": p, "label": f"{path} from {project}", "dirty": False})
        return res

    def _code_install(self, project, packages):
        from .code import CodeWorkspace
        self.code = self.code or CodeWorkspace()
        return self.code.install(project, packages)

    def _draft_email(self, subject="", body="", to=""):
        from urllib.parse import quote
        url = f"mailto:{quote(to or '', safe='@,')}?subject={quote(subject or '')}&body={quote((body or '')[:1800])}"
        subprocess.Popen(["open", url] if MAC else ["xdg-open", url])
        return True, f"opened an email draft titled {subject!r}; the user reviews and sends it"

    def _open_file(self, path, app=""):
        from .files import resolve_file
        f = resolve_file(path, getattr(self, "default_save_dir", ""))
        if MAC:
            cmd = ["open", "-a", MAC_NAMES.get(app.lower().strip(), app), str(f)] if app else ["open", str(f)]
        else:
            cmd = ["xdg-open", str(f)]
        subprocess.Popen(cmd)
        return True, f"opened {f}" + (f" in {app}" if app else "")

    # ---- macOS: see and drive windows ----------------------------------------------------
    def _list_windows(self):
        from . import mac
        from ..guards import redact_title
        rows = []
        for line in mac.list_windows()[:40]:
            title, _, proc = line.rpartition(" | ")
            rows.append(f"{redact_title(title)} | {proc}")
        return True, "\n".join(rows) or "(no windows)"

    def _focus_window(self, title):
        from . import mac
        from ..guards import redact_title
        got = mac.focus(title)
        if not got:
            return False, f"no window matching {title!r}"
        return True, "focused: " + redact_title(got.rpartition(" | ")[0]) + " | " + got.rpartition(" | ")[2]

    def _read_text(self, title=""):
        from . import mac
        from ..guards import is_sensitive
        if title:
            mac.focus(title)
            time.sleep(0.3)
        _, t = mac.front()
        if is_sensitive(t):
            return True, "[sensitive window: contents not read]"
        text = mac.focused_text()
        return True, (f"document in {t}:\n{text[:4000]}" if text else f"no readable text found in {t}")

    def _read_window(self, title=""):
        return self._read_text(title)

    def _click(self, name, window=""):
        from . import mac
        from ..guards import check_click, check_not_sensitive
        if window:
            mac.focus(window)
            time.sleep(0.3)
        proc, t = mac.front()
        check_not_sensitive(t)
        check_click(name, proc)
        return (True, f"clicked {name!r} in {t}") if mac.click(name) else (False, f"no control named {name!r} in {t}")

    # ---- documents -----------------------------------------------------------------
    def _word_new_document(self):
        self.doc_parts = []
        return True, "started a new document (saved as .docx when you save it)"

    def _word_insert_text(self, text):
        self.doc_parts.append(text)
        return True, f"added {len(text.split())} words; verified: kept in the document"

    def _word_save(self, filename):
        from docx import Document
        from .files import out_dir, safe_name, unique_path
        p = unique_path(out_dir(), safe_name(filename, (".docx",), ".docx"))
        d = Document()
        for part in self.doc_parts or [""]:
            for para in part.split("\n"):
                d.add_paragraph(para)
        d.save(str(p))
        subprocess.Popen(["open", str(p)] if MAC else ["xdg-open", str(p)])
        self.last_docx = p
        return True, f"saved {p} and opened it"

    def _export_pdf(self):
        from . import mac
        base = getattr(self, "last_docx", None)
        if base is None:
            return False, "save the document first (word_save), then export"
        pdf = base.with_suffix(".pdf")
        if not mac.app_running("Microsoft Word"):
            return False, "PDF export needs Microsoft Word for Mac; the .docx is saved and open"
        mac.word_save_pdf(str(pdf))
        subprocess.Popen(["open", str(pdf)])
        return True, f"saved and opened {pdf}"

    def capture_screen(self) -> dict:
        """macOS: front window title and text, plus a screenshot (deleted right after)."""
        import base64
        import io
        import tempfile
        from ..guards import is_sensitive
        title, text, app = "", "", ""
        if MAC:
            from . import mac
            app, title = mac.front()
            if is_sensitive(title):
                return {"blocked": True, "title": "[private window]"}
            text = mac.focused_text()
        img = None
        f = os.path.join(tempfile.gettempdir(), "lazymonster-look.jpg")
        try:
            if MAC:
                subprocess.run(["screencapture", "-x", "-t", "jpg", f], timeout=10)
            if os.path.exists(f):
                from PIL import Image
                im = Image.open(f).convert("RGB")
                im.thumbnail((1400, 1400))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=80)
                img = base64.b64encode(buf.getvalue()).decode()
        finally:
            try:
                os.remove(f)
            except OSError:
                pass
        return {"title": title, "app": app, "text": text[:8000], "image": img}

    def owned_items(self):
        live = []
        for o in self.owned:
            if o["kind"] == "proc" and o["proc"].poll() is not None:
                continue
            live.append(o)
        self.owned = live
        return live

    def save_item(self, o, path):
        raise RuntimeError("on macOS the app itself asks where to save when it closes")

    def close_item(self, o, discard_prompt=True):
        if o["kind"] == "proc":
            o["proc"].terminate()
            return f"stopped {o['label']}"
        from . import mac
        mac.quit_app(o["app"])
        return f"quit {o['app']} (it asks about anything unsaved)"

    def _make_presentation(self, filename, outline):
        from ..office_docs import build_pptx
        from .files import out_dir, safe_name, unique_path
        p = unique_path(out_dir(), safe_name(filename, (".pptx",), ".pptx"))
        build_pptx(filename, outline, p)
        return self._open_file(str(p))

    def _finish(self, summary="", next=""):
        return True, summary or "done"

    # ---- system ------------------------------------------------------------------------
    def _volume_set(self, level):
        if MAC:
            _osa(f"set volume output volume {int(level)}")
        else:
            _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{int(level)}%"])
        return True, f"volume {level}"

    def _mute(self):
        _osa("set volume with output muted") if MAC else _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"])
        return True, "muted"

    def _unmute(self):
        _osa("set volume without output muted") if MAC else _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
        return True, "unmuted"

    def _media_play_pause(self):
        return self._player("play-pause")

    def _media_next(self):
        return self._player("next")

    def _media_prev(self):
        return self._player("previous")

    def _player(self, cmd):
        if MAC or not shutil.which("playerctl"):
            return False, "media keys need playerctl on Linux; not yet on macOS"
        _run(["playerctl", cmd])
        return True, cmd

    def _lock(self):
        _run(["pmset", "displaysleepnow"]) if MAC else _run(["loginctl", "lock-session"])
        return True, "locked"


def json_str(s: str) -> str:
    import json
    return json.dumps(s)
