# install_uruk_relay.ps1 — copies uruk-relay skill into Claude skills directory

$src = "C:\uruk-trinity-console\uruk-relay-SKILL.md"
$skillsBase = "$env:APPDATA\Claude\local-agent-mode-sessions\skills-plugin"

# Find the skills dir (there may be nested session IDs)
$skillDirs = Get-ChildItem -Path $skillsBase -Recurse -Filter "skills" -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName "docx") } |
    Select-Object -First 1

if (-not $skillDirs) {
    Write-Host "ERROR: Cannot find skills directory under $skillsBase" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

$dest = Join-Path $skillDirs.FullName "uruk-relay"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Path $src -Destination (Join-Path $dest "SKILL.md") -Force

Write-Host "OK: uruk-relay skill installed to:" -ForegroundColor Green
Write-Host "    $dest" -ForegroundColor Cyan
Write-Host ""
Write-Host "Restart Claude Desktop (or reload skills) to activate /uruk-relay" -ForegroundColor Yellow
Read-Host "Press Enter to exit"
