"""Run Lazy-Monster in the background from sign-in, per user.

A real Windows *service* runs in session 0 with no microphone or desktop, so this
is the standard alternative for voice assistants: a user-level startup entry
(HKCU\\...\\Run) that launches the windowless build (monsterw.exe) at sign-in.
No admin rights needed; nothing runs for other users."""
import os
import subprocess
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "LazyMonster"


def launcher() -> str:
    scripts = Path(sys.executable).parent
    w = scripts / "monsterw.exe"
    if w.exists():
        return f'"{w}" ui --background'
    pyw = scripts / "pythonw.exe"
    return f'"{pyw}" -m lazymonster.cli ui --background'


PLIST_LABEL = "com.lazymonster.agent"


def _plist_path():
    return Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


def installed() -> str:
    if sys.platform == "darwin":
        p = _plist_path()
        return str(p) if p.exists() else ""
    if os.name != "nt":
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, VALUE)[0]
    except OSError:
        return ""


def install() -> str:
    if sys.platform == "darwin":
        return _install_mac()
    import winreg
    cmd = launcher()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, cmd)
    return cmd


def uninstall() -> bool:
    if sys.platform == "darwin":
        p = _plist_path()
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(p)], capture_output=True)
        existed = p.exists()
        p.unlink(missing_ok=True)
        return existed
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, VALUE)
        return True
    except OSError:
        return False


def _matches() -> list:
    import psutil
    out = []
    for p in psutil.process_iter(["pid", "name", "cmdline", "ppid"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
        except Exception:
            continue
        if "--background" in cl and ("monsterw" in cl.lower() or "lazymonster" in cl.lower()) and p.pid != os.getpid():
            out.append(p)
    return out


def running() -> list:
    """One entry per monster. On Windows each one is a chain of three processes
    (monsterw.exe -> venv pythonw -> real pythonw), so only the top of each chain counts."""
    procs = _matches()
    pids = {p.pid for p in procs}
    return [p for p in procs if p.info.get("ppid") not in pids]


def start() -> None:
    if sys.platform == "darwin":
        subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{PLIST_LABEL}"], capture_output=True)
        if not running():
            subprocess.Popen([sys.executable, "-m", "lazymonster.cli", "ui", "--background"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return
    import shlex
    parts = shlex.split(launcher(), posix=False)
    subprocess.Popen([x.strip('"') for x in parts], creationflags=0x00000008 | 0x00000200,   # DETACHED | NEW_GROUP
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def stop() -> int:
    from .config import config_dir
    config_dir().mkdir(parents=True, exist_ok=True)
    (config_dir() / "stop.flag").touch()                 # tell the watchdog this one is on purpose
    tops = running()
    for p in _matches():                 # the whole chain, children included
        try:
            p.terminate()
        except Exception:
            pass
    return len(tops)


_MUTEX = None


def single_instance(kind: str = "background") -> bool:
    """True if this is the only background monster (or its supervisor) for this user."""
    global _MUTEX
    if os.name != "nt":
        import fcntl
        from .config import config_dir
        config_dir().mkdir(parents=True, exist_ok=True)
        _MUTEX = open(config_dir() / f"{kind}.lock", "w")
        try:
            fcntl.flock(_MUTEX, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)       # read the error the right way (0.8 did not)
    k32.CreateMutexW.restype = ctypes.c_void_p
    _MUTEX = k32.CreateMutexW(None, False, "Local\\LazyMonster" + kind.capitalize())
    return ctypes.get_last_error() != 183                        # ERROR_ALREADY_EXISTS


def _install_mac() -> str:
    """A LaunchAgent: macOS's standard way to start a user app at login."""
    import plistlib
    from .config import config_dir
    config_dir().mkdir(parents=True, exist_ok=True)
    p = _plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    app_exe = Path.home() / "Applications" / "Lazy-Monster.app" / "Contents" / "MacOS" / "Lazy-Monster"
    # through Lazy-Monster.app, so the permissions you granted to "Lazy-Monster" apply to the background copy
    prog = [str(app_exe), "ui", "--background"] if app_exe.exists() else [sys.executable, "-m", "lazymonster.cli", "ui", "--background"]
    plist = {"Label": PLIST_LABEL, "ProgramArguments": prog, "LimitLoadToSessionType": "Aqua",
             "RunAtLoad": True, "KeepAlive": False, "ProcessType": "Interactive",
             "StandardOutPath": str(config_dir() / "launchd.log"), "StandardErrorPath": str(config_dir() / "launchd.log")}
    with open(p, "wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(p)], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(p)], capture_output=True)
    return str(p)
