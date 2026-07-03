$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv-training\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Training Python not found. Run training/bootstrap_windows.ps1 first."
}

& $Python -X utf8 (Join-Path $PSScriptRoot "controller_shadow_server.py")
