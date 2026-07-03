param(
    [string]$PythonVersion = "3.11",
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu128",
    [switch]$SkipPythonInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv-training"

function Find-TrainingPython {
    $knownPaths = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:ProgramFiles "Python311\python.exe")
    )
    foreach ($path in $knownPaths) {
        if (Test-Path $path) {
            return $path
        }
    }

    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        $candidate = & py "-$PythonVersion" -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $candidate) {
            return $candidate.Trim()
        }
    }
    finally {
        $ErrorActionPreference = $oldPreference
    }
    return $null
}

$PythonExe = Find-TrainingPython
if (-not $PythonExe -and -not $SkipPythonInstall) {
    Write-Host "Installing Python $PythonVersion for the isolated training environment..."
    & py install $PythonVersion
    if ($LASTEXITCODE -ne 0) {
        throw "Python $PythonVersion installation failed."
    }
    $PythonExe = Find-TrainingPython
}

if (-not $PythonExe) {
    throw "Python $PythonVersion is not available. Install it or run without -SkipPythonInstall."
}

if (-not (Test-Path $Venv)) {
    & $PythonExe -m venv $Venv
}

$VenvPython = Join-Path $Venv "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip wheel setuptools
& $VenvPython -m pip install torch --index-url $TorchIndexUrl
& $VenvPython -m pip install -r (Join-Path $PSScriptRoot "requirements-training.txt")
& $VenvPython -X utf8 (Join-Path $PSScriptRoot "preflight.py")

Write-Host ""
Write-Host "Training environment ready:"
Write-Host "  $VenvPython -X utf8 training\train_qlora.py"
