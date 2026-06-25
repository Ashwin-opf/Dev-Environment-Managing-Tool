# PC Doctor - Windows first-time setup script.
# Runs correctly under: powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
$ErrorActionPreference = "Stop"

function Info($msg)  { Write-Host "[ok] $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "[!] $msg"  -ForegroundColor Yellow }
function Err($msg)   { Write-Host "[x] $msg"  -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  PC Doctor - Windows Setup" -ForegroundColor Cyan
Write-Host "  -------------------------------------"

# Refresh PATH so freshly installed tools are visible in this session
function Refresh-Env {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") +
                ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}
Refresh-Env

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir    = Split-Path -Parent $ScriptDir
$BackendDir = Join-Path $RootDir "backend"

# --- Python ------------------------------------------------------------------
# Prefer the Windows Py Launcher (py.exe) over bare 'python' to avoid the
# Windows App Execution Alias stub that silently opens the Microsoft Store.
function Find-Python {
    try {
        $v = & py -3 --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -like "Python *") { return "py -3" }
    } catch {}
    try {
        $v = & python --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -like "Python *") { return "python" }
    } catch {}
    return $null
}

$PythonCmd = Find-Python
if (-not $PythonCmd) {
    Warn "Python not found. Installing Python 3.12 via Winget..."
    winget install --id Python.Python.3.12 --exact --silent
    Refresh-Env
    $PythonCmd = Find-Python
    if (-not $PythonCmd) { Err "Python installation failed. Please install Python 3.12+ manually." }
}
$pyVer = if ($PythonCmd -eq "py -3") { & py -3 --version 2>$null } else { & python --version 2>$null }
Info "Python found: $pyVer"

# --- Node.js -----------------------------------------------------------------
$NodeValid = $false
try {
    $nv = & node --version 2>$null
    if ($LASTEXITCODE -eq 0) { $NodeValid = $true; Info "Node found: $nv" }
} catch {}

if (-not $NodeValid) {
    Warn "Node.js not found. Installing via Winget..."
    winget install --id OpenJS.NodeJS.LTS --exact --silent
    Refresh-Env
    try {
        $nv = & node --version 2>$null
        if ($LASTEXITCODE -eq 0) { $NodeValid = $true; Info "Node found: $nv" }
    } catch {}
    if (-not $NodeValid) { Err "Node.js installation failed. Please install Node.js 18+ manually." }
}

# --- Python virtual environment ----------------------------------------------
$VenvDir    = Join-Path $BackendDir ".venv"
$VenvPip    = Join-Path $VenvDir "Scripts\pip.exe"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvDir)) {
    Info "Creating Python virtual environment..."
    if ($PythonCmd -eq "py -3") {
        & py -3 -m venv $VenvDir
    } else {
        & python -m venv $VenvDir
    }
}

Info "Installing Python backend dependencies..."
$env:PYTHONIOENCODING = "utf-8"
& $VenvPip install --quiet -r (Join-Path $BackendDir "requirements.txt")

Info "Populating repair knowledge database..."
& $VenvPython (Join-Path $BackendDir "populate_db.py")

Info "Installing Node app dependencies..."
Push-Location $RootDir
npm.cmd install
Pop-Location

Write-Host ""
Info "Setup complete. Run: npm.cmd run start"
Write-Host ""
