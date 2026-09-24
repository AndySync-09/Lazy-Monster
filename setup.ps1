# Creates .venv next to this script and installs Lazy-Monster into it. Safe to re-run.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "python not found on PATH (need 3.11+)" }
$ok = & python -c "import sys; print(sys.version_info >= (3, 11))"
if ($ok -ne "True") { throw "Python 3.11+ required; found $(& python --version)" }
if (-not (Test-Path .\.venv\Scripts\python.exe)) { & python -m venv .venv }
else {
  # a running background copy locks monsterw.exe and breaks the reinstall: stop it first
  try { & .\.venv\Scripts\python.exe -m lazymonster.cli service stop *> $null } catch { }
  try { Get-Process monsterw -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue } catch { }
  Start-Sleep -Seconds 1
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]" --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
Write-Host "`nInstalled into $PSScriptRoot\.venv`n"
& .\.venv\Scripts\monster.exe doctor
