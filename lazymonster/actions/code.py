"""VS Code workspace tools. Projects live in Documents\\LazyMonster\\code\\<project>.
Files are written progressively so you watch the code appear in the editor."""
import os
import shutil
import subprocess
import time
from pathlib import Path

from ..guards import safe_project, safe_rel_path
from .files import out_dir

NO_WINDOW = 0x08000000


def code_root() -> Path:
    d = out_dir() / "code"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_vscode():
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe"
    mac = Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")
    for p in (local, Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft VS Code" / "Code.exe", mac):
        if p.is_file():
            return str(p)
    return shutil.which("code")


MANIFEST = ".lazymonster.json"


def _sha(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest(folder: Path) -> dict:
    import json
    m = folder / MANIFEST
    try:
        return json.loads(m.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _record(folder: Path, rel: str, target: Path) -> None:
    import json
    m = _manifest(folder)
    m[rel] = _sha(target)
    (folder / MANIFEST).write_text(json.dumps(m, indent=1), encoding="utf-8")


def venv_dir(folder: Path) -> Path:
    """Project environments live in %LOCALAPPDATA%, not next to the code: the code folder
    is often OneDrive-synced, and OneDrive locks files while a venv is being created."""
    from ..models import models_dir
    return models_dir().parent / "venvs" / folder.name


def project_python(folder: Path) -> Path:
    """Each project gets its own virtual environment; packages never touch Lazy-Monster's or the system's."""
    import sys
    venv = venv_dir(folder)
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        venv.parent.mkdir(parents=True, exist_ok=True)
        base = getattr(sys, "_base_executable", None) or sys.executable      # the real Python, not our venv's shim
        r = subprocess.run([base, "-m", "venv", str(venv)], capture_output=True, text=True, timeout=240)
        if r.returncode != 0 or not py.exists():
            raise RuntimeError(f"could not create the project environment: {(r.stderr or r.stdout).strip()[-400:]}")
    return py


class CodeWorkspace:
    def __init__(self, stream_delay: float = 0.03, lines_per_tick: int = 2):
        self.opened = set()
        self.delay, self.step = stream_delay, lines_per_tick

    def _launch(self, *args):
        exe = find_vscode()
        if not exe:
            raise FileNotFoundError("VS Code not found (install it or add 'code' to PATH)")
        subprocess.Popen([exe, *args], creationflags=NO_WINDOW if os.name == "nt" else 0,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def open(self, project: str) -> str:
        folder = code_root() / safe_project(project)
        folder.mkdir(parents=True, exist_ok=True)
        self._launch("-n", str(folder))
        self.opened.add(str(folder))
        time.sleep(2.5)                          # let the window come up
        return f"opened {folder} in VS Code"

    def write(self, project: str, path: str, content: str) -> str:
        folder = code_root() / safe_project(project)
        rel = safe_rel_path(path)
        target = folder / Path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        if str(folder) not in self.opened:
            self.open(project)
        target.write_text("", encoding="utf-8")
        self._launch("-r", "-g", str(target))    # show the file in the project window
        time.sleep(1.0)
        lines = content.splitlines(keepends=True)
        for i in range(self.step, len(lines) + self.step, self.step):
            target.write_text("".join(lines[:i]), encoding="utf-8")
            time.sleep(self.delay)
        target.write_text(content, encoding="utf-8")
        _record(folder, rel, target)
        back = target.read_text(encoding="utf-8")
        note = "verified on disk" if back == content else "MISMATCH on disk; write it again"
        if target.suffix == ".py" and back == content:
            try:
                compile(content, str(target), "exec")
                note += "; Python syntax OK"
            except SyntaxError as e:
                note += f"; SYNTAX ERROR line {e.lineno}: {e.msg}. Fix it with another code_write_file"
        return f"wrote {len(lines)} lines to {target}; {note}"

    # ---- running and packages (the agent asks the user before either) ----
    def run(self, project: str, path: str, wait: float = 4.0) -> tuple:
        """Run a .py file the monster wrote, unchanged since, in its own window.
        Not a shell: fixed interpreter, file inside the sandbox, no arguments."""
        from ..guards import GuardError
        folder = code_root() / safe_project(project)
        rel = safe_rel_path(path)
        target = folder / Path(rel)
        if target.suffix != ".py":
            raise GuardError("only .py files can be run")
        if not target.is_file():
            raise GuardError(f"{rel} does not exist in {project}")
        if _manifest(folder).get(rel) != _sha(target):
            raise GuardError(f"{rel} was not written by Lazy-Monster (or was changed since); it will not run it")
        py = project_python(folder)
        log = folder / ".run.log"
        flags = 0x00000010 if os.name == "nt" else 0          # CREATE_NEW_CONSOLE: visible window for output
        with open(log, "w", encoding="utf-8") as err:
            proc = subprocess.Popen([str(py), "-X", "utf8", str(target)], cwd=str(folder), stderr=err,
                                    creationflags=flags)
        self.last_proc = proc
        time.sleep(wait)
        code = proc.poll()
        tail = log.read_text(encoding="utf-8", errors="replace").strip()[-1500:]
        if code is None:
            return True, f"{rel} is running (pid {proc.pid}); its window should be open"
        if code == 0:
            return True, f"{rel} finished (exit 0)" + (f"; stderr: {tail}" if tail else "")
        hint = ""
        if "ModuleNotFoundError" in tail:
            import re
            m = re.search(r"No module named '([^'.]+)", tail)
            hint = f" Missing package: install it with code_install('{project}', '{m.group(1) if m else ''}')."
        return False, f"{rel} crashed (exit {code}): {tail}{hint}"

    def install(self, project: str, packages: str) -> tuple:
        from ..guards import safe_packages
        folder = code_root() / safe_project(project)
        folder.mkdir(parents=True, exist_ok=True)
        pkgs = safe_packages(packages)
        py = project_python(folder)
        r = subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", *pkgs],
                           capture_output=True, text=True, timeout=600,
                           creationflags=NO_WINDOW if os.name == "nt" else 0)
        tail = (r.stdout + r.stderr).strip()[-800:]
        return (r.returncode == 0), (f"installed {' '.join(pkgs)} into the {project} environment" if r.returncode == 0
                                     else f"pip failed: {tail}")
