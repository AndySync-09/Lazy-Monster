# Lazy-Monster: one-command installer for Windows 10/11.
#
#   irm https://raw.githubusercontent.com/AndySync-09/lazy-monster/main/install.ps1 | iex
#
# Installs to %LOCALAPPDATA%\LazyMonster (no admin rights). Re-run it any time to update;
# your settings, voiceprint and downloaded models are kept.
# Optional, set before running (skips the questions):
#   $env:LM_BRAIN = "keep" | "openai" | "claude" | "local", $env:LM_LOCAL_URL, $env:LM_LOCAL_MODEL, $env:LM_GO_BIG = "1",
#   $env:LM_JEV = "y" | "n"
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

  # 1. The brain (first, so nothing installs until the monster can think) -------------------------
  Step 1 "The monster's brain"
  function User-Key($name) { $v = [Environment]::GetEnvironmentVariable($name, "Process"); if (-not $v) { $v = [Environment]::GetEnvironmentVariable($name, "User") }; return $v }
  function Saved-Setting($name) {
    $f = Join-Path $env:APPDATA "lazymonster\settings.toml"
    if (Test-Path $f) { $m = Select-String -Path $f -Pattern ("^" + $name + ' = "?([^"]*)"?') | Select-Object -First 1; if ($m) { return $m.Matches[0].Groups[1].Value } }
    return ""
  }
  function Find-Local {
    $out = @()
    foreach ($c in @(@("Ollama", "http://localhost:11434/v1"), @("llama.cpp", "http://localhost:8080/v1"), @("vLLM", "http://localhost:8000/v1"), @("LM Studio", "http://localhost:1234/v1"))) {
      try { $r = Invoke-RestMethod -Uri ($c[1] + "/models") -TimeoutSec 2; $ids = @($r.data | ForEach-Object { $_.id }) ; if ($ids.Count -gt 0) { $out += [pscustomobject]@{ name = $c[0]; url = $c[1]; models = $ids } } } catch { }
    }
    return $out
  }
  function Test-Tools($url, $model, $key) {
    $body = @{ model = $model; messages = @(@{ role = "user"; content = "Call the ping tool now." })
               tools = @(@{ type = "function"; function = @{ name = "ping"; description = "Reply to a ping"; parameters = @{ type = "object"; properties = @{} } } }) } | ConvertTo-Json -Depth 8
    try {
      $h = @{}; if ($key) { $h.Authorization = "Bearer $key" }
      $r = Invoke-RestMethod -Method Post -Uri ($url.TrimEnd("/") + "/chat/completions") -Headers $h -ContentType "application/json" -Body $body -TimeoutSec 120
      return [bool]($r.choices[0].message.tool_calls)
    } catch { return $false }
  }

  $brainKind = ""; $localUrl = ""; $localModel = ""; $goBig = $false
  $saved = Saved-Setting "planner"
  $have = @{ openai = [bool](User-Key "OPENAI_API_KEY"); anthropic = [bool](User-Key "ANTHROPIC_API_KEY"); local = [bool](Saved-Setting "local_base_url") }
  $current = if ($saved -and $saved -ne "none" -and $have[$saved]) { $saved } elseif ($have.openai) { "openai" } elseif ($have.anthropic) { "anthropic" } else { "" }
  $label = @{ openai = "OpenAI (GPT)"; anthropic = "Claude (Anthropic)"; local = "a local model at " + (Saved-Setting "local_base_url") }
  $choice = $env:LM_BRAIN
  if ($current -and -not $choice) {
    Write-Host ""
    Write-Host ("      Monster Brain: " + $label[$current]) -ForegroundColor Green
    Write-Host "      1  Keep it" -ForegroundColor White
    Write-Host "      2  Switch brain" -ForegroundColor White
    Write-Host "      3  Make the monster go big (hard tasks use a stronger model; costs more)" -ForegroundColor White
    $k = Read-Host "      Pick 1-3 [1]"
    if ($k -eq "3") { $brainKind = $current; $goBig = $true }
    elseif ($k -ne "2") { $brainKind = $current; $goBig = ((Saved-Setting "go_big") -eq "true") }
    if ($brainKind -eq "local") { $localUrl = Saved-Setting "local_base_url"; $localModel = Saved-Setting "local_model" }
  } elseif ($choice -in @("keep", "openai", "claude", "anthropic", "local", "none")) {
    $brainKind = @{ keep = $current; openai = "openai"; claude = "anthropic"; anthropic = "anthropic"; local = "local"; none = "none" }[$choice]
    if ($brainKind -eq "local") { $localUrl = if ($env:LM_LOCAL_URL) { $env:LM_LOCAL_URL } else { Saved-Setting "local_base_url" }; $localModel = if ($env:LM_LOCAL_MODEL) { $env:LM_LOCAL_MODEL } else { Saved-Setting "local_model" } }
    $goBig = ($env:LM_GO_BIG -eq "1") -or ((Saved-Setting "go_big") -eq "true")
  }

  while (-not $brainKind) {
    Write-Host ""
    Note "The monster needs a brain to plan real tasks. Pick one:"
    Write-Host "      1  OpenAI (GPT)                         your OpenAI API key" -ForegroundColor White
    Write-Host "      2  Claude (Anthropic)                   your Anthropic API key" -ForegroundColor White
    Write-Host "      3  Local model (Ollama, llama.cpp, vLLM, LM Studio)   runs on your machine" -ForegroundColor White
    Write-Host "      q  Quit the installer" -ForegroundColor DarkGray
    $k = Read-Host "      Pick 1-3"
    if ($k -eq "q") { Write-Host "  No brain, no monster. Run this again when you have a key or a local model." -ForegroundColor Yellow; return }
    if ($k -eq "1" -or $k -eq "2") {
      $kind = if ($k -eq "1") { "openai" } else { "anthropic" }
      $envn = @{ openai = "OPENAI_API_KEY"; anthropic = "ANTHROPIC_API_KEY" }[$kind]
      $key = User-Key $envn
      if (-not $key) { $key = Ask-Secret "Paste your $envn (hidden)" }
      if (-not $key) { continue }
      Write-Host "      Checking the key..." -ForegroundColor DarkGray -NoNewline
      if (Test-Brain $kind $key "") {
        Write-Host " works." -ForegroundColor Green
        [Environment]::SetEnvironmentVariable($envn, $key, "User"); Set-Item -Path "Env:$envn" -Value $key
        $brainKind = $kind
      } else { Write-Host " that key didn't work (wrong key or offline). Try again." -ForegroundColor Yellow }
    } elseif ($k -eq "3") {
      Write-Host "      Looking for local model servers..." -ForegroundColor DarkGray
      $found = @(Find-Local)
      $i = 1
      foreach ($f in $found) { Write-Host ("      $i  " + $f.name + "  " + $f.url + "  (" + ($f.models -join ", ") + ")") -ForegroundColor White; $i++ }
      Write-Host "      u  Enter an endpoint URL myself" -ForegroundColor White
      $pick = Read-Host "      Pick"
      if ($pick -eq "u" -or $found.Count -eq 0) {
        if ($found.Count -eq 0) { Note "None found on the usual ports (11434, 8080, 8000, 1234). Start one, or type its URL." }
        $localUrl = (Read-Host "      Endpoint URL (e.g. http://192.168.1.20:8000/v1)").Trim().TrimEnd("/")
        try { $r = Invoke-RestMethod -Uri ($localUrl + "/models") -TimeoutSec 5; $models = @($r.data | ForEach-Object { $_.id }) } catch { $models = @() }
      } else {
        $f = $found[[int]$pick - 1]; $localUrl = $f.url; $models = @($f.models)
      }
      if ($models.Count -gt 1) {
        $i = 1; foreach ($m in $models) { Write-Host "      $i  $m" -ForegroundColor White; $i++ }
        $mp = Read-Host "      Which model? [1]"; if (-not $mp) { $mp = "1" }; $localModel = $models[[int]$mp - 1]
      } elseif ($models.Count -eq 1) { $localModel = $models[0] }
      else { $localModel = Read-Host "      Model name" }
      $lkey = User-Key "LOCAL_LLM_API_KEY"
      Write-Host "      Testing that $localModel can use tools (needed to drive your apps)..." -ForegroundColor DarkGray -NoNewline
      if (Test-Tools $localUrl $localModel $lkey) {
        Write-Host " it can." -ForegroundColor Green; $brainKind = "local"
      } else {
        Write-Host " it didn't call the tool." -ForegroundColor Yellow
        Note "llama.cpp: start llama-server with --jinja.  vLLM: --enable-auto-tool-choice --tool-call-parser <yours>."
        Note "Ollama / LM Studio: pick a model with tool support (for example qwen3, llama3.1, mistral-nemo)."
        $anyway = Read-Host "      Use it anyway? It can talk but may fail at actions. [y/N]"
        if ($anyway -match "^[yY]") { $brainKind = "local" }
      }
    }
    if ($brainKind) {
      $bigHint = @{ openai = "GPT-6 Astra"; anthropic = "Claude Sonnet 5"; local = "a cloud model (needs an OpenAI or Anthropic key)" }[$brainKind]
      $gb = Read-Host "      Make the monster go big on hard tasks with $bigHint? Costs more per hard task. [y/N]"
      $goBig = $gb -match "^[yY]"
    }
  }
  Note ("Monster Brain: " + $brainKind + $(if ($brainKind -eq "local") { " ($localModel at $localUrl)" } else { "" }) + $(if ($goBig) { ", goes big on hard tasks" } else { "" }))


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
  if ($brainKind -eq "local") {
    & $Py -c "from lazymonster.config import save_setting as s; s('local_base_url', r'$localUrl'); s('local_model', r'$localModel')"
  }
  & $Py -c "from lazymonster.config import save_setting as s; s('go_big', $(if ($goBig) { 'True' } else { 'False' }))"
  $decider = if ($useJev) { "jev" } else { "" }
  & $Py -c "from lazymonster.config import save_setting as s; s('decider', '$decider')"
  Note ("Brain: $brainKind" + $(if ($useJev) { " + Jev" } else { "" }))

  # 5. Models and your voice ------------------------------------------------------------
  Step 5 "Voice models (about 1.9 GB, one time)"
  & $Monster models --quiet; Check-Exit "Downloading the voice models"
  Step 6 "Teach it your voice"
  $wakeModel = Join-Path $env:LOCALAPPDATA "lazymonster\models\wakeword\hey_monster.npz"
  if ($env:LM_SKIP_VOICE -ne "1") {
    $train = $true
    if (Test-Path $wakeModel) {
      Write-Host "      You already taught it your voice." -ForegroundColor Green
      Write-Host "      1  Keep it" -ForegroundColor White
      Write-Host "      2  Start fresh (forget it and retrain, about 5 minutes)" -ForegroundColor White
      $v = Read-Host "      Pick 1-2 [1]"
      $train = ($v -eq "2")
      if ($train) { & $Monster voice-reset }
    } else {
      $ans = Read-Host "      Train your wake word and voice lock now? Recommended, about 5 minutes. [Y/n]"
      $train = $ans -notmatch "^[nN]"
    }
    if ($train) {
      & $Monster wake-train; Check-Exit "Training the wake word"
      & $Monster voice-enroll
      if ($LASTEXITCODE -ne 0) { Note "Voice lock is off for now (it never locks you out). Try again later: monster voice-enroll" }
    } elseif (-not (Test-Path $wakeModel)) { Note "Later: monster voice-reset --train" }
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
