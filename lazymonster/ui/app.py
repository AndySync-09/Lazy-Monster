"""pywebview shell: one frameless always-on-top window. The engine talks to the
page through UIBus events; the page talks back through Api (text, approve,
cancel, sleep). The page never executes anything itself."""
import base64
import json
import threading
from pathlib import Path


class UIBus:
    def __init__(self):
        self.window = None
        self.ready = threading.Event()
        self.pending = []
        self.lock = threading.Lock()
        self.agent = None
        self.geom = None                        # {"full": (x, y, w, h), "orb": (x, y, w, h)}
        self.orb = False

    def set_orb(self, on: bool):
        """Shrink to a small sleeping orb at the screen edge, or back to the full window."""
        if on == self.orb or self.window is None:
            return
        self.orb = on
        self.emit({"type": "orb", "on": on})
        try:
            if self.geom:
                x, y, w, h = self.geom["orb" if on else "full"]
                self.window.resize(w, h)
                self.window.move(x, y)
            if not on:
                self.window.show()
        except Exception:
            pass

    def attach(self, window):
        self.window = window
        window.events.loaded += self._loaded

    def _loaded(self):
        self.ready.set()
        with self.lock:
            q, self.pending = self.pending, []
        for ev in q:
            self._send(ev)

    def _send(self, ev):
        js = f"window.lm&&lm.event({json.dumps(ev)})"
        try:
            (getattr(self.window, "run_js", None) or self.window.evaluate_js)(js)
        except Exception:
            pass

    def emit(self, ev: dict):
        if not self.ready.is_set():
            with self.lock:
                self.pending.append(ev)
            return
        self._send(ev)

    # ---- adapters for the engine's feedback / log / say hooks ----------------
    def feedback(self, kind: str):
        # Screen state comes from conversation.py; this only adds the extras (buttons, check mark).
        if kind == "confirm":
            self.emit({"type": "confirm"})
        elif kind in ("ok", "error"):
            self.emit({"type": "done", "ok": kind == "ok"})
            s = getattr(self.agent, "suggestion", "") if self.agent else ""
            if kind == "ok" and s:
                self.emit({"type": "suggest", "text": s})
        elif kind == "unknown":
            self.emit({"type": "note", "text": "didn't catch that"})

    def log(self, line: str):
        ev = json.loads(line)
        e = ev.get("event")
        if e == "task":
            self.emit({"type": "task", "text": ev.get("text", "")})
        elif e == "agent_think":
            chosen = [c for c in ev.get("chosen", []) if c and c != "finish"]
            if chosen or ev.get("candidates"):
                self.emit({"type": "decide", "candidates": ev.get("candidates", []), "chosen": chosen})
        elif e == "step":
            msg = str(ev.get("msg", ""))
            blocked = "GuardError" in msg or "not allowed" in msg or "sensitive" in msg
            self.emit({"type": "step", "tool": ev.get("intent"), "ok": bool(ev.get("ok")), "blocked": blocked,
                       "msg": msg.split("->")[-1].strip()[:140]})
        elif e == "agent_done" and ev.get("s") is not None:
            self.emit({"type": "note", "text": f"{ev.get('steps')} steps \u00b7 {ev.get('s')} s"})
        elif e == "asking":
            self.emit({"type": "ask"})
        elif e == "refined":
            self.emit({"type": "heard", "text": ev.get("accurate", ""), "final": True})
        elif e == "dispatched":
            self.emit({"type": "task", "text": f"{ev.get('intent')} {ev.get('args', {})}"})

    def say(self, text: str):
        self.emit({"type": "say", "text": text})


class Api:
    """Exposed to the page. pywebview publishes every public attribute to
    JavaScript (recursively), so everything except the three methods must be
    private: otherwise it walks the native window object forever, and the page
    could reach engine internals."""

    def __init__(self, engine, stop: threading.Event, bus: UIBus, speaker=None, conv=None):
        self._engine, self._stop, self._bus, self._speaker, self._conv = engine, stop, bus, speaker, conv

    def talk(self):
        if self._conv is not None:
            threading.Thread(target=self._conv.push_to_talk, daemon=True).start()

    def submit(self, text):
        threading.Thread(target=self._engine.handle_text, args=(str(text)[:2000],), daemon=True).start()

    def sleep(self):
        self._stop.set()

    def hide(self):
        try:
            self._bus.window.hide()
        except Exception:
            pass

    def stop_talking(self):
        if self._speaker is not None:
            self._speaker.interrupt()

    def compact(self, on):
        try:
            self._bus.window.resize(400, 470 if on else 760)
        except Exception:
            pass


def page_html() -> str:
    here = Path(__file__).parent
    font = base64.b64encode((here / "SpaceGrotesk.ttf").read_bytes()).decode()
    return (here / "index.html").read_text(encoding="utf-8").replace("{{FONT}}", font)


def run_window(bus: UIBus, api: Api, backend, stop: threading.Event, hidden: bool = False):
    """Blocks on the main thread (pywebview requirement); backend runs alongside."""
    import webview
    x = y = None
    try:
        s = webview.screens[0]
        x, y = s.width - 420, max(0, s.height - 820)
        bus.geom = {"full": (x, y, 400, 760), "orb": (s.width - 190, max(0, s.height - 250), 170, 180)}
    except Exception:
        pass
    win = webview.create_window("Lazy-Monster", html=page_html(), js_api=api, width=400, height=760,
                                x=x, y=y, frameless=True, on_top=True, easy_drag=True, resizable=False,
                                background_color="#0D1117", hidden=hidden)
    bus.attach(win)

    def main():
        backend()
        stop.wait()
        try:
            win.destroy()
        except Exception:
            pass

    webview.start(main)
