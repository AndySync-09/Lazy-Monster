# Lazy-Monster: one-command installer for Windows 10/11.
#
#   irm https://raw.githubusercontent.com/AndySync-09/lazy-monster/main/install.ps1 | iex
#
# Installs to %LOCALAPPDATA%\LazyMonster (no admin rights). Re-run it any time to update;
# your settings, voiceprint and downloaded models are kept.
# Optional, set before running:  $env:LM_BRAIN = "openai" | "claude" | "none", $env:LM_JEV = "y" | "n"  (skip the questions)
#   $env:OPENAI_API_KEY / ANTHROPIC_API_KEY / TYPESAFE_API_KEY,
#   $env:LM_SKIP_VOICE = "1", $env:LM_ZIP = "C:\path\lazy-monster.zip" (install from a local zip)
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

  function Step($n, $text) { Write-Host ""; Write-Host "  [$n/7] $text" -ForegroundColor Green }
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

  function Monster($sleepy) {
    $eyes = if ($sleepy) { "(-)   (-)" } else { "(o)   (o)" }
    $z = if ($sleepy) { "      z" } else { "" }
    Write-Host ""
    Write-Host "        /\           /\$z" -ForegroundColor Green
    Write-Host "       /  \_________/  \" -ForegroundColor Magenta
    Write-Host "      |    $eyes    |" -ForegroundColor Magenta
    Write-Host "      |        v        |" -ForegroundColor Magenta
    Write-Host "       \_______________/" -ForegroundColor Magenta
  }
  function Ask-Secret($prompt) {
    $sec = Read-Host "      $prompt" -AsSecureString
    return [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)).Trim()
  }
  function Test-Brain($kind, $key, $url) {
    try {
      if ($kind -eq "openai") { Invoke-RestMethod -Uri "https://api.openai.com/v1/models" -Headers @{ Authorization = "Bearer $key" } -TimeoutSec 15 | Out-Null }
      elseif ($kind -eq "anthropic") { Invoke-RestMethod -Uri "https://api.anthropic.com/v1/models" -Headers @{ "x-api-key" = $key; "anthropic-version" = "2023-06-01" } -TimeoutSec 15 | Out-Null }
      elseif ($kind -eq "jev") {
        $body = '{"state":"Turn the volume down please.","model":"jev-latest","questions":{"q":{"type":"noul","instructions":"Is this a request?"}}}'
        Invoke-RestMethod -Method Post -Uri "https://api.typesafe.ai/v1/systemone" -Headers @{ Authorization = "Bearer $key" } -ContentType "application/json" -Body $body -TimeoutSec 15 | Out-Null
      }
      return $true
    } catch { return $false }
  }

  Monster $true
  Write-Host ""
  Write-Host "  Lazy-Monster installer" -ForegroundColor Magenta
  Write-Host "  Say it. The monster does it." -ForegroundColor DarkGray

  # 1. The brain (first, so nothing installs until you've chosen) -------------------------------
  Step 1 "Choose the monster's brain"
  Note "It plans bigger tasks with an AI model you bring. Instant commands (mute, open apps) work without one."
  Write-Host ""
  Write-Host "      1  OpenAI (GPT)          you need an OpenAI API key" -ForegroundColor White
  Write-Host "      2  Claude (Anthropic)    you need an Anthropic API key" -ForegroundColor White
  Write-Host "      3  None for now          instant commands only" -ForegroundColor White
  $brain = $env:LM_BRAIN
  if (-not $brain) { $brain = Read-Host "      Pick 1-3 [1]" }
  $brainKind = switch ($brain) { "2" { "anthropic" } "claude" { "anthropic" } "anthropic" { "anthropic" } "3" { "none" } "none" { "none" } default { "openai" } }
  $brainEnv = @{ openai = "OPENAI_API_KEY"; anthropic = "ANTHROPIC_API_KEY" }[$brainKind]
  if ($brainKind -ne "none") {
    $existing = [Environment]::GetEnvironmentVariable($brainEnv, "User")
    $key = [Environment]::GetEnvironmentVariable($brainEnv, "Process")
    if (-not $key -and $existing) { $key = $existing; Note "Found your $brainEnv. Keeping it." }
    if (-not $key) { $key = Ask-Secret "Paste your $brainEnv (hidden)" }
    if ($key) {
      Write-Host "      Checking the key..." -ForegroundColor DarkGray -NoNewline
      if (Test-Brain $brainKind $key "") { Write-Host " works." -ForegroundColor Green }
      else { Write-Host " couldn't confirm it (offline or wrong key). Saving anyway; 'monster doctor' checks again later." -ForegroundColor Yellow }
      [Environment]::SetEnvironmentVariable($brainEnv, $key, "User"); Set-Item -Path "Env:$brainEnv" -Value $key
    } else {
      Note "No key given: installing with instant commands only. Add one later by running this installer again."
      $brainKind = "none"
    }
  }

  # Jev (TypeSafe) is optional: fast yes/no and choice decisions next to the brain
  $useJev = $false
  Write-Host ""
  Note "Optional: Jev by TypeSafe makes the quick calls (was that meant for me? which tool? did you say yes?)"
  Note "in milliseconds, so the monster ignores room chatter and starts hard jobs on the right model."
  $ansJ = if ($env:LM_JEV) { $env:LM_JEV } else { Read-Host "      Add Jev? You need a TypeSafe API key (console.typesafe.ai). [y/N]" }
  if ($ansJ -match "^[yY1]") {
    $jkey = [Environment]::GetEnvironmentVariable("TYPESAFE_API_KEY", "Process")
    if (-not $jkey) { $jkey = [Environment]::GetEnvironmentVariable("TYPESAFE_API_KEY", "User") }
    if (-not $jkey) { $jkey = Ask-Secret "Paste your TYPESAFE_API_KEY (hidden)" }
    if ($jkey) {
      Write-Host "      Asking Jev a test question..." -ForegroundColor DarkGray -NoNewline
      if (Test-Brain "jev" $jkey "") { Write-Host " it answered." -ForegroundColor Green }
      else { Write-Host " no answer yet (offline or wrong key). Saving anyway; the monster works without it." -ForegroundColor Yellow }
      [Environment]::SetEnvironmentVariable("TYPESAFE_API_KEY", $jkey, "User"); $env:TYPESAFE_API_KEY = $jkey
      $useJev = $true
    }
  }

  # 1. Python -----------------------------------------------------------------------
  Step 2 "Checking for Python 3.11 or newer"
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
  Step 3 "Getting Lazy-Monster"
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
  Step 4 "Installing (its own private Python environment)"
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

  # save the brain choice now that the program is installed
  & $Py -c "from lazymonster.config import save_setting as s; s('planner', '$brainKind')"; Check-Exit "Saving your brain choice"
  $decider = if ($useJev) { "jev" } else { "" }
  & $Py -c "from lazymonster.config import save_setting as s; s('decider', '$decider')"
  Note ("Brain: $brainKind" + $(if ($useJev) { " + Jev" } else { "" }))

  # 5. Models and your voice ------------------------------------------------------------
  Step 5 "Voice models (about 1.9 GB, one time)"
  & $Monster models --quiet; Check-Exit "Downloading the voice models"
  Step 6 "Teach it your voice"
  if ($env:LM_SKIP_VOICE -ne "1") {
    $ans = Read-Host "      Train your wake word and voice lock now? Recommended, about 4 minutes. [Y/n]"
    if ($ans -notmatch "^[nN]") {
      & $Monster wake-train; Check-Exit "Training the wake word"
      & $Monster voice-enroll
      if ($LASTEXITCODE -ne 0) { Note "Voice lock is off for now (it never locks you out). Try again later: monster voice-enroll" }
    } else { Note "Later: monster wake-train ; monster voice-enroll" }
  }

  # 6. Start ----------------------------------------------------------------------------
  Step 7 "Waking the monster"
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

  Monster $false
  Write-Host ""
  Write-Host "  Done. Say ""Hey Monster"", or press Ctrl+Alt+Space." -ForegroundColor Magenta
  Write-Host "  Pick a voice: monster voices    Check everything: monster doctor" -ForegroundColor DarkGray
  Write-Host "  Update later by running the same command. Remove with: $App\uninstall.ps1" -ForegroundColor DarkGray
  Write-Host ""
}
