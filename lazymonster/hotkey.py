"""Push-to-talk: a global hotkey (default Ctrl+Alt+Space) that starts listening,
no wake word needed. Pressing it means you are at the keyboard, so that request
skips the voice lock."""
import threading

MODS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
KEYS = {"space": 0x20, "enter": 0x0D, "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
        "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B}


def parse(combo: str):
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty hotkey")
    *mods, key = parts
    if not mods:
        raise ValueError("a hotkey needs at least one modifier (ctrl, alt, shift, win)")
    m = 0
    for x in mods:
        if x not in MODS:
            raise ValueError(f"unknown modifier {x}")
        m |= MODS[x]
    if key in KEYS:
        vk = KEYS[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise ValueError(f"unknown key {key}")
    return m | 0x4000, vk                                  # MOD_NOREPEAT


def start(combo: str, on_press) -> bool:
    import os
    import sys
    if not combo:
        return False
    if sys.platform == "darwin":
        return _start_mac(combo, on_press)
    if os.name != "nt":
        return False
    mods, vk = parse(combo)
    ok = threading.Event()
    result = {}

    def loop():
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        result["ok"] = bool(user32.RegisterHotKey(None, 0x4C4D, mods, vk))
        ok.set()
        if not result["ok"]:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312:                          # WM_HOTKEY
                try:
                    on_press()
                except Exception:
                    pass

    threading.Thread(target=loop, daemon=True, name="lazymonster-hotkey").start()
    ok.wait(2)
    return result.get("ok", False)


def to_pynput(combo: str) -> str:
    """"cmd+shift+space" -> "<cmd>+<shift>+<space>" (pynput's format)."""
    names = {"ctrl": "<ctrl>", "control": "<ctrl>", "alt": "<alt>", "option": "<alt>", "shift": "<shift>",
             "cmd": "<cmd>", "win": "<cmd>", "space": "<space>", "enter": "<enter>"}
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError("a hotkey needs a modifier and a key")
    out = []
    for p in parts:
        if p in names:
            out.append(names[p])
        elif len(p) == 1 and p.isalnum():
            out.append(p)
        elif p.startswith("f") and p[1:].isdigit():
            out.append(f"<{p}>")
        else:
            raise ValueError(f"unknown key {p}")
    return "+".join(out)


def _start_mac(combo: str, on_press) -> bool:
    """macOS asks once for Input Monitoring / Accessibility permission for this."""
    try:
        from pynput import keyboard
        listener = keyboard.GlobalHotKeys({to_pynput(combo): on_press})
        listener.daemon = True
        listener.start()
        return True
    except Exception:
        return False
