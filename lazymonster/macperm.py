"""macOS permissions, the easy way.

macOS never lets an app switch its own privacy permissions on; the user has to say yes. What we can do
is make that one click: each check below asks macOS for the permission the official way, so a
"Lazy-Monster would like to…" dialog appears (or Lazy-Monster is already listed in the right pane with
its switch ready), and then we wait and tick it off the moment it's on. Everything runs inside
Lazy-Monster.app, so the prompts and the switches say Lazy-Monster, not Python or Terminal."""
import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

BUNDLE = Path.home() / "Applications" / "Lazy-Monster.app"
EXE = BUNDLE / "Contents" / "MacOS" / "Lazy-Monster"
PANE = "x-apple.systempreferences:com.apple.preference.security?"


def in_bundle() -> bool:
    return os.environ.get("LM_BUNDLE") == "1"


def _lib(path):
    try:
        return ctypes.cdll.LoadLibrary(path)
    except OSError:
        return None


_CG = _lib("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
_IOK = _lib("/System/Library/Frameworks/IOKit.framework/IOKit")


# --- the five permissions: (check) -> True/False/None(unknown), (ask) -> shows the macOS prompt ---
def mic_ok():
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        return {3: True, 2: False, 1: False}.get(int(AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)))
    except Exception:
        return None


def mic_ask():
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, lambda ok: None)
    except Exception:           # no AVFoundation bridge: opening the mic triggers the same prompt
        try:
            import sounddevice as sd
            with sd.InputStream(channels=1, samplerate=16000):
                time.sleep(0.3)
        except Exception:
            pass


def ax_ok():
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return None


def ax_ask():
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True})   # adds Lazy-Monster to the list
    except Exception:
        pass


def screen_ok():
    if not _CG:
        return None
    _CG.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
    return bool(_CG.CGPreflightScreenCaptureAccess())


def screen_ask():
    if _CG:
        _CG.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
        _CG.CGRequestScreenCaptureAccess()


def keys_ok():
    if not _IOK:
        return None
    _IOK.IOHIDCheckAccess.restype = ctypes.c_uint32
    return {0: True, 1: False}.get(int(_IOK.IOHIDCheckAccess(ctypes.c_uint32(1))))   # 1 = listen events


def keys_ask():
    if _IOK:
        _IOK.IOHIDRequestAccess.restype = ctypes.c_bool
        _IOK.IOHIDRequestAccess(ctypes.c_uint32(1))


def auto_run():
    r = subprocess.run(["osascript", "-e", 'tell application "System Events" to get name of first process'],
                       capture_output=True, text=True, timeout=90)
    return r.returncode == 0


ITEMS = [
    # name, why, pane, check, ask, needs a switch flipped by hand after the prompt
    ("Microphone", "so it can hear you", "Privacy_Microphone", mic_ok, mic_ask, False),
    ("Accessibility", "so it can click and type for you", "Privacy_Accessibility", ax_ok, ax_ask, True),
    ("Screen Recording", "so it can read your screen when you ask", "Privacy_ScreenCapture", screen_ok, screen_ask, True),
    ("Input Monitoring", "for the push-to-talk shortcut", "Privacy_ListenEvent", keys_ok, keys_ask, True),
]


def status() -> dict:
    return {name: check() for name, _w, _p, check, _a, _m in ITEMS}


def _wait(check, secs):
    end = time.time() + secs
    while time.time() < end:
        if check():
            return True
        time.sleep(0.7)
    return bool(check())


def guided() -> int:
    """Ask for each permission; wait for the yes; move on. Returns how many are still missing."""
    print("\n  macOS asks you once for each of these. Lazy-Monster is already in each list: just say yes.\n")
    missing = 0
    for name, why, pane, check, ask, manual in ITEMS:
        if check():
            print(f"  ✓ {name}: already on")
            continue
        print(f"  → {name}: {why}")
        ask()
        if manual:
            time.sleep(0.8)
            subprocess.run(["open", PANE + pane])
            print("     Flip the switch next to Lazy-Monster (Touch ID or your password confirms it). Waiting…")
        else:
            print("     Click Allow in the macOS dialog. Waiting…")
        if _wait(check, 120):
            print(f"  ✓ {name}: on")
        elif name == "Screen Recording" and check() is False:
            print("  ✓ Screen Recording: if you switched it on, it starts working the next time the monster starts")
        else:
            missing += 1
            print(f"  ! {name}: not yet. Run 'monster permissions' any time to finish.")
    print("  → Automation: so it can drive apps like Finder, Word and PowerPoint")
    print("     Click OK in the macOS dialog (each app asks once, the first time it's used). Waiting…")
    try:
        ok = auto_run()
    except subprocess.TimeoutExpired:
        ok = False
    print("  ✓ Automation: on" if ok else "  ! Automation: not yet. It will ask again the first time it's needed.")
    missing += 0 if ok else 1
    subprocess.run(["osascript", "-e", 'tell application "Terminal" to activate'], capture_output=True)
    print("\n  All set." if missing == 0 else f"\n  {missing} still to do; 'monster permissions' picks up where you left off.")
    return missing


def relaunch_in_bundle(args) -> int | None:
    """Run this command again inside Lazy-Monster.app (so macOS asks on behalf of Lazy-Monster)."""
    if in_bundle() or not EXE.exists():
        return None
    return subprocess.call([str(EXE), *args])
