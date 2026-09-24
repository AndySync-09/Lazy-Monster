"""Keeps the background monster alive. The sign-in entry starts this small supervisor;
it runs the real monster as a child and, if the child dies without you quitting it,
saves a crash report (the last log lines, the exit code, any native crash trace)
and starts it again, up to 5 times in 10 minutes."""
import os
import subprocess
import sys
import time
from pathlib import Path

from .config import config_dir

CHILD_ENV = "LM_SUPERVISED"
MAX_RESTARTS, WINDOW = 5, 600.0


def crash_dir() -> Path:
    d = config_dir() / "crashes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_report(code: int, started: float) -> Path:
    log = config_dir() / "monster.log"
    tail = ""
    try:
        tail = "\n".join(log.read_text(encoding="utf-8-sig", errors="replace").splitlines()[-120:])
    except OSError:
        pass
    p = crash_dir() / time.strftime("crash-%Y%m%d-%H%M%S.txt")
    from . import __version__
    p.write_text(f"Lazy-Monster {__version__}\nexit code: {code} ({code & 0xFFFFFFFF:#010x})\n"
                 f"ran for: {int(time.time() - started)} s\n\n--- last log lines ---\n{tail}\n", encoding="utf-8")
    reports = sorted(crash_dir().glob("crash-*.txt"))
    for old in reports[:-20]:
        old.unlink(missing_ok=True)
    return p


def supervise(argv) -> int:
    from .service import single_instance
    if not single_instance("supervisor"):
        return 0
    restarts = []
    report = ""
    (config_dir() / "stop.flag").unlink(missing_ok=True)
    flags = 0x08000000 if os.name == "nt" else 0
    while True:
        env = dict(os.environ, **{CHILD_ENV: "1"})
        if report:
            env["LM_RESTARTED"] = report
        started = time.time()
        code = subprocess.call([sys.executable, "-m", "lazymonster.cli", *argv], env=env, creationflags=flags)
        stop_flag = config_dir() / "stop.flag"
        if code == 0 or stop_flag.exists():
            stop_flag.unlink(missing_ok=True)
            return 0                                             # you quit it, or `monster service stop`
        report = str(write_report(code, started))
        now = time.time()
        restarts = [t for t in restarts if now - t < WINDOW] + [now]
        if len(restarts) > MAX_RESTARTS:
            return code                                          # something is badly wrong; don't loop forever
        time.sleep(3)
