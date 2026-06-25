# PC Doctor - Windows start script.
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir    = Split-Path -Parent $ScriptDir

# Refresh PATH so node/npm installed in this session are visible
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") +
            ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

if (-not (Test-Path (Join-Path $RootDir "node_modules"))) {
    Write-Host "[!] Node dependencies are missing. Run: powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path (Join-Path $RootDir "backend\.venv"))) {
    Write-Host "[!] Python backend environment is missing. Run: powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1" -ForegroundColor Yellow
    exit 1
}

Write-Host "[PC Doctor] Launching..." -ForegroundColor Cyan
Set-Location $RootDir
# Use npm.cmd (the .cmd wrapper) to bypass PowerShell script execution policy
npm.cmd run dev
