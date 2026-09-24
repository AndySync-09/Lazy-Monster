# Removes Lazy-Monster for this user. Run:  powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\LazyMonster\app\uninstall.ps1"
& {
  $Root = Join-Path $env:LOCALAPPDATA "LazyMonster"
  $App = Join-Path $Root "app"
  $Py = Join-Path $App ".venv\Scripts\python.exe"
  if (Test-Path $Py) { try { & $Py -m lazymonster.cli service uninstall } catch { } }
  Get-Process monsterw -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  Remove-Item (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Lazy-Monster.lnk") -ErrorAction SilentlyContinue
  $scripts = Join-Path $App ".venv\Scripts"
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  [Environment]::SetEnvironmentVariable("Path", (($userPath -split ";" | Where-Object { $_ -and $_ -ne $scripts }) -join ";"), "User")
  Set-Location $env:USERPROFILE
  Remove-Item $App -Recurse -Force -ErrorAction SilentlyContinue          # the program itself
  $ans = Read-Host "Also delete your settings, voiceprint, journal and downloaded models? [y/N]"
  if ($ans -match "^[yY]") {
    Remove-Item (Join-Path $env:APPDATA "lazymonster") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $Root -Recurse -Force -ErrorAction SilentlyContinue       # models, project environments
  }
  Write-Host "Lazy-Monster removed. Your files in Documents\LazyMonster and C:\temp were not touched."
}
