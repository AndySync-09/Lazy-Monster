# Lazy-Monster: one-command installer for Windows 10/11.
#
#   irm https://raw.githubusercontent.com/AndySync-09/lazy-monster/main/install.ps1 | iex
#
# Installs to %LOCALAPPDATA%\LazyMonster (no admin rights). Re-run it any time to update;
# your settings, voiceprint and downloaded models are kept.
# Optional, set before running:  $env:OPENAI_API_KEY = "sk-..."  |  $env:LM_SKIP_VOICE = "1"  |  $env:LM_ZIP = "C:\path\lazy-monster.zip"
& {
  $ErrorActionPreference = "Stop"
  $ProgressPreference = "SilentlyContinue"
  $Repo = if ($env:LM_REPO) { $env:LM_REPO } else { "AndySync-09/lazy-monster" }
  $Ref  = if ($env:LM_REF)  { $env:LM_REF }  else { "main" }
  $Root = Join-Path $env:LOCALAPPDATA "LazyMonster"
  $App  = Join-Path $Root "app"
  $Venv = Join-Path $App ".venv"
  $Py   = Join-Path $Venv "Scripts\python.exe"
  $Monster = Join-Path $Venv "Scripts\monster.exe"

  function Step($n, $text) { Write-Host ""; Write-Host "[$n/6] $text" -ForegroundColor Green }
  function Note($text) { Write-Host "      $text" -ForegroundColor Gray }
  function Check-Exit($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" } }

  function Find-Python {
    $tries = @(@("py", "-3.12"), @("py", "-3.13"), @("py", "-3.11"), @("python"), @("python3"))
    foreach ($t in $tries) {
      if (-not (Get-Command $t[0] -ErrorAction SilentlyContinue)) { continue }
      $extra = @()
      if ($t.Count -gt 1) { $extra += $t[1] }
      try {
        $out = & $t[0] @extra -c "import sys; print(sys.version_info[0]*100+sys.version_info[1]); print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out -and $out.Count -ge 2 -and [int]$out[0] -ge 311) { return $out[1] }
      } catch { }
    }
    foreach ($v in @("Python313", "Python312", "Python311")) {
      $p = Join-Path $env:LOCALAPPDATA "Programs\Python\$v\python.exe"
      if (Test-Path $p) { return $p }
    }
    return $null
  }

  Write-Host ""
  Write-Host "  Lazy-Monster installer" -ForegroundColor Magenta
  Write-Host "  Say it. The monster does it." -ForegroundColor DarkGray

  # 1. Python -----------------------------------------------------------------------
  Step 1 "Checking for Python 3.11 or newer"
  $base = Find-Python
  if (-not $base) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
      throw "Python 3.11+ is needed. Install it from https://www.python.org/downloads/ and run this command again."
    }
    Note "Installing Python 3.12 for your user (winget)..."
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Null
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $base = Find-Python
    if (-not $base) { throw "Python was installed but can't be found yet. Open a new PowerShell window and run the command again." }
  }
  Note "Using $base"

  # 2. Download ---------------------------------------------------------------------
  Step 2 "Getting Lazy-Monster"
  if (Test-Path $Py) {
    Note "Stopping the running copy so it can be updated..."
    try { & $Py -m lazymonster.cli service stop *> $null } catch { }
    Get-Process monsterw -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
  }
  $zip = $env:LM_ZIP
  if (-not $zip) {
    $zip = Join-Path $env:TEMP "lazy-monster.zip"
    Invoke-WebRequest -UseBasicParsing -Uri "https://codeload.github.com/$Repo/zip/refs/heads/$Ref" -OutFile $zip
  }
  $tmp = Join-Path $env:TEMP ("lazy-monster-" + [guid]::NewGuid().ToString("N"))
  Expand-Archive -Path $zip -DestinationPath $tmp -Force
  $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
  if (-not (Test-Path (Join-Path $src.FullName "pyproject.toml"))) { $src = Get-Item $tmp }
  New-Item -ItemType Directory -Force -Path $App | Out-Null
  Get-ChildItem $App -Force | Where-Object { $_.Name -ne ".venv" } | Remove-Item -Recurse -Force   # old program files only
  Copy-Item -Path (Join-Path $src.FullName "*") -Destination $App -Recurse -Force
  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
  Note "Installed files in $App"

  # 3. Install ----------------------------------------------------------------------
  Step 3 "Installing (its own private Python environment)"
  if (-not (Test-Path $Py)) { & $base -m venv $Venv; Check-Exit "Creating the environment" }
  & $Py -m pip install --upgrade pip --quiet --disable-pip-version-check; Check-Exit "Updating pip"
  & $Py -m pip install $App --quiet --disable-pip-version-check; Check-Exit "Installing dependencies"
  & $Py -m pip install --force-reinstall --no-deps $App --quiet --disable-pip-version-check; Check-Exit "Installing Lazy-Monster"
  $scripts = Join-Path $Venv "Scripts"
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  if (-not ($userPath -split ";" | Where-Object { $_ -eq $scripts })) {
    [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $scripts), "User")
    Note "Added 'monster' to your PATH (new terminals)"
  }
  $env:Path = $env:Path + ";" + $scripts

  # 4. Key --------------------------------------------------------------------------
  Step 4 "OpenAI API key (for bigger tasks)"
  $existing = [Environment]::GetEnvironmentVariable("OPENAI_API_KEY", "User")
  if ($env:OPENAI_API_KEY -and -not $existing) {
    [Environment]::SetEnvironmentVariable("OPENAI_API_KEY", $env:OPENAI_API_KEY, "User"); $existing = $env:OPENAI_API_KEY
  }
  if ($existing) {
    Note "Already set. Keeping it."
  } else {
    $sec = Read-Host "      Paste your OpenAI API key, or press Enter to skip (instant commands work without it)" -AsSecureString
    $key = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    if ($key) {
      [Environment]::SetEnvironmentVariable("OPENAI_API_KEY", $key.Trim(), "User"); $env:OPENAI_API_KEY = $key.Trim()
      Note "Saved for your Windows user."
    } else { Note "Skipped. Add it later with: monster doctor" }
  }

  # 5. Models and your voice ------------------------------------------------------------
  Step 5 "Voice models (about 1.9 GB, one time) and your voice"
  & $Monster models --quiet; Check-Exit "Downloading the voice models"
  if ($env:LM_SKIP_VOICE -ne "1") {
    $ans = Read-Host "      Teach it your voice now? Recommended, about 3 minutes with your mic. [Y/n]"
    if ($ans -notmatch "^[nN]") {
      & $Monster wake-train; Check-Exit "Training the wake word"
      & $Monster voice-enroll; Check-Exit "Recording your voiceprint"
    } else { Note "Later: monster wake-train ; monster voice-enroll" }
  }

  # 6. Start ----------------------------------------------------------------------------
  Step 6 "Starting Lazy-Monster in the background"
  & $Monster service install; Check-Exit "Starting the background service"
  try {
    $lnk = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Lazy-Monster.lnk"
    $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $sc.TargetPath = Join-Path $scripts "monsterw.exe"
    $sc.Arguments = "ui"
    $sc.WorkingDirectory = $App
    $sc.IconLocation = Join-Path $App "docs\assets\brand\lazy-monster.ico"
    $sc.Description = "Lazy-Monster voice agent"
    $sc.Save()
    Note "Added Lazy-Monster to the Start menu"
  } catch { Note "Could not add a Start menu shortcut (not needed)." }

  Write-Host ""
  Write-Host "  Done. Say ""Hey Monster"", or press Ctrl+Alt+Space." -ForegroundColor Magenta
  Write-Host "  Update later by running the same command. Remove with: $App\uninstall.ps1" -ForegroundColor DarkGray
  Write-Host ""
}
