"""System tray: show/hide the window, pause listening, pick the voice, open
folders and settings, sleep. Changes persist to settings.toml."""
import os
import threading
from pathlib import Path

VOICES = [("af_heart", "Heart (US)"), ("af_bella", "Bella (US)"), ("af_nicole", "Nicole (US, soft)"),
          ("bf_emma", "Emma (UK)"), ("hf_alpha", "Alpha (Indian English)"), ("hf_beta", "Beta (Indian English)")]


def _open(path):
    path = str(path)
    if os.name == "nt":
        os.startfile(path)
    else:
        import subprocess
        import sys
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


class Tray:
    def __init__(self, bus, speaker, gate, detector_ref, stop: threading.Event, on_train=None, conv=None, engine=None):
        self.bus, self.speaker, self.gate, self.det, self.stop = bus, speaker, gate, detector_ref, stop
        self.conv, self.engine = conv, engine
        self._saved_verify = None
        self.visible, self.paused, self.icon = True, False, None

    def start(self):
        import pystray
        from PIL import Image
        from ..actions.files import out_dir
        from ..config import config_dir, save_setting

        def show_window(icon, item):
            try:
                self.bus.window.show()
            except Exception:
                pass

        def hide_window(icon, item):
            try:
                self.bus.window.hide()
            except Exception:
                pass

        def toggle_pause(icon, item):
            self.paused = not self.paused
            self.gate.set("paused", self.paused)
            d = self.det.get("detector")
            if d is not None:
                d.paused = self.paused
            self.bus.emit({"type": "state", "state": "sleep",
                           "sub": "listening paused (tray)" if self.paused else 'say "Hey Monster"'})

        def voice_item(key, label):
            def pick(icon, item):
                k = getattr(self.speaker, "kokoro", None)
                if k is not None:
                    k.voice = key
                save_setting("kokoro_voice", key)
                threading.Thread(target=self.speaker.say, args=(f"Hi, this is {label.split(' (')[0]}.",), daemon=True).start()
            return pystray.MenuItem(label, pick, checked=lambda item: getattr(getattr(self.speaker, "kokoro", None), "voice", "") == key,
                                    radio=True)

        def open_settings(icon, item):
            p = config_dir() / "settings.toml"
            if not p.exists():
                save_setting("ui", True)
            _open(p)

        def talk(icon, item):
            if self.conv is not None:
                self.conv.push_to_talk()

        def toggle_lock(icon, item):
            e = self.engine
            if e is None:
                return
            if e.verify is not None:
                self._saved_verify, e.verify = e.verify, None
            elif self._saved_verify is not None:
                e.verify = self._saved_verify
            save_setting("voice_lock", e.verify is not None)

        def retrain(icon, item):
            import subprocess
            import sys
            exe = str(Path(sys.executable).with_name("monster.exe"))
            subprocess.Popen(["cmd", "/c", "start", "Retrain Lazy-Monster", exe, "voice-reset", "--train"])

        menu = pystray.Menu(
            pystray.MenuItem("Show Lazy-Monster", show_window, default=True),
            pystray.MenuItem("Talk now", talk),
            pystray.MenuItem("Settings…", lambda icon, item: (show_window(icon, item),
                                                               self.bus.emit({"type": "open_settings"}))),
            pystray.MenuItem("Hide window", hide_window),
            pystray.MenuItem("Back to the corner", lambda icon, item: self.bus.back_to_corner()),
            pystray.MenuItem("Pause listening", toggle_pause, checked=lambda item: self.paused),
            pystray.MenuItem("Stop talking", lambda icon, item: self.speaker.interrupt()),
            pystray.MenuItem("Voice lock (only my voice)", toggle_lock,
                             checked=lambda item: bool(self.engine and self.engine.verify is not None)),
            pystray.MenuItem("Voice", pystray.Menu(*[voice_item(k, l) for k, l in VOICES])),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open LazyMonster folder", lambda icon, item: _open(out_dir())),
            pystray.MenuItem("Open settings", open_settings),
            pystray.MenuItem("Open history log", lambda icon, item: _open(config_dir() / "log.jsonl")),
            pystray.MenuItem("Retrain my voice…", retrain),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Lazy-Monster", lambda icon, item: self.stop.set()),
        )
        ico = Path(__file__).parent / "monster.ico"
        img = Image.open(ico if ico.exists() else Path(__file__).parent / "icon.png")
        self.icon = pystray.Icon("lazy-monster", img, "Lazy-Monster", menu)
        self.icon.run_detached()
        return self

    def close(self):
        try:
            self.icon and self.icon.stop()
        except Exception:
            pass
