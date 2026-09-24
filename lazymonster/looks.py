"""The mascot's skin, seasonal outfit, and desktop-pet walk."""
import datetime as _dt
import random
import threading
import time


def seasonal(today: _dt.date = None) -> str:
    """Outfit for the season when set to automatic."""
    d = today or _dt.date.today()
    md = (d.month, d.day)
    if (10, 20) <= md <= (11, 15):
        return "diwali"
    if md >= (12, 15) or md <= (1, 2):
        return "santa"
    if (3, 20) <= md <= (5, 31):
        return "cricket"
    if md == (12, 31) or md == (1, 1):
        return "party"
    return ""


def outfit(cfg) -> str:
    return seasonal() if cfg.outfit == "auto" else cfg.outfit


def skin_event(cfg) -> dict:
    return {"type": "skin", "skin": cfg.skin, "outfit": outfit(cfg)}


def follow_cursor(bus, stop: threading.Event, clock=time.monotonic) -> None:
    """Windows: tell the mascot where your pointer is (even outside its window), ~8 times a second."""
    import os
    if os.name != "nt":
        return
    import win32api

    def loop():
        last = (9, 9)
        while not stop.is_set():
            time.sleep(0.12)
            if bus.window is None or not bus.geom:
                continue
            try:
                px, py = win32api.GetCursorPos()
                x, y, w, h = bus.geom["orb" if bus.orb else "full"]
                cx, cy = x + w / 2, y + (h * 0.5 if bus.orb else 230)
                dx = max(-1.0, min(1.0, (px - cx) / 700))
                dy = max(-1.0, min(1.0, (py - cy) / 500))
                if abs(dx - last[0]) > 0.03 or abs(dy - last[1]) > 0.03:
                    last = (dx, dy)
                    bus.emit({"type": "cursor", "dx": round(dx, 2), "dy": round(dy, 2)})
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True, name="lazymonster-eyes").start()


class Pet:
    """While the monster naps as the small orb, it strolls along the top of the taskbar,
    stops to nap now and then, and turns around at the screen edges."""

    def __init__(self, bus, cfg, stop: threading.Event):
        self.bus, self.cfg, self.stop = bus, cfg, stop
        self.x, self.dir, self.walking = None, 1, False

    def _colorkey(self, on: bool) -> None:
        import os
        if os.name != "nt" or self.bus.window is None:
            return
        try:
            import win32api
            import win32con
            import win32gui
            from .ui.app import _hwnd
            hwnd = _hwnd(self.bus.window)
            ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            if on:
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex | win32con.WS_EX_LAYERED)
                win32gui.SetLayeredWindowAttributes(hwnd, win32api.RGB(1, 2, 3), 0, win32con.LWA_COLORKEY)
            else:
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex & ~win32con.WS_EX_LAYERED)
        except Exception:
            pass

    def run(self) -> None:
        def loop():
            active = False
            pause_until = 0.0
            while not self.stop.is_set():
                time.sleep(0.06)
                on = bool(self.cfg.pet_mode and self.bus.orb and self.bus.geom and self.bus.window is not None)
                if on != active:
                    active = on
                    self._colorkey(on)
                    self.bus.emit({"type": "pet", "on": on, "walking": False, "dir": self.dir})
                    if not on:
                        self.x = None
                        continue
                if not on:
                    continue
                sw, sh = self.bus.geom.get("screen", (1920, 1080))
                ox, oy, ow, oh = self.bus.geom["orb"]
                if self.x is None:
                    self.x = ox
                now = time.monotonic()
                if now < pause_until:
                    continue
                if random.random() < 0.004:                      # stop for a nap
                    pause_until = now + random.uniform(4, 12)
                    self.walking = False
                    self.bus.emit({"type": "pet", "on": True, "walking": False, "dir": self.dir})
                    continue
                if not self.walking:
                    self.walking = True
                    if random.random() < 0.3:
                        self.dir *= -1
                    self.bus.emit({"type": "pet", "on": True, "walking": True, "dir": self.dir})
                self.x += 3 * self.dir
                if self.x < 8 or self.x > sw - ow - 8:
                    self.dir *= -1
                    self.x = max(8, min(sw - ow - 8, self.x))
                    self.bus.emit({"type": "pet", "on": True, "walking": True, "dir": self.dir})
                try:
                    self.bus.window.move(int(self.x), int(oy))
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True, name="lazymonster-pet").start()
