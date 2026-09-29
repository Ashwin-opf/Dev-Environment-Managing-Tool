"""
create_portable_package.py — Assemble PC Doctor Windows Portable Distribution
"""

import os
import shutil
import zipfile
import hashlib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PORTABLE_DIR = ROOT_DIR / "dist_portable" / "PC_Doctor_Portable"
ZIP_OUTPUT = ROOT_DIR / "PC_Doctor_WINDOWS_PORTABLE.zip"

def assemble_portable():
    print(f"Assembling Windows Portable Distribution into: {PORTABLE_DIR}")
    
    if PORTABLE_DIR.exists():
        shutil.rmtree(PORTABLE_DIR)
    PORTABLE_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Copy backend binary & runtime
    backend_src = ROOT_DIR / "dist" / "pc-doctor-backend"
    backend_dst = PORTABLE_DIR / "pc-doctor-backend"
    if backend_src.exists():
        print("Copying standalone pc-doctor-backend...")
        shutil.copytree(backend_src, backend_dst)
    else:
        print(f"Warning: {backend_src} does not exist!")
        
    # 2. Copy frontend dist
    frontend_src = ROOT_DIR / "frontend" / "dist"
    frontend_dst = PORTABLE_DIR / "frontend-dist"
    if frontend_src.exists():
        print("Copying frontend-dist...")
        shutil.copytree(frontend_src, frontend_dst)
    else:
        print(f"Warning: {frontend_src} does not exist!")
        
    # 3. Copy resources
    resources_dst = PORTABLE_DIR / "resources"
    resources_dst.mkdir(parents=True, exist_ok=True)
    for db_name in ["knowledge.db", "knowledge_static.db", "pkg_catalog.json"]:
        src_file = ROOT_DIR / "backend" / db_name
        if src_file.exists():
            shutil.copy2(src_file, resources_dst / db_name)
            # Also ensure in backend_dst
            if backend_dst.exists():
                shutil.copy2(src_file, backend_dst / db_name)
                
    # 4. Create run_portable.bat
    run_bat_content = """@echo off
setlocal
title PC Doctor — Portable Edition

echo ========================================================
echo        PC Doctor — Intelligent System Repair
echo                Portable Edition v1.0.0-rc.1
echo ========================================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "API_HOST=127.0.0.1"
set "API_PORT=8765"
set "PC_DOCTOR_PACKAGED=1"
set "FRONTEND_DIST=%SCRIPT_DIR%frontend-dist"

echo [1/3] Starting PC Doctor backend server...
if exist "pc-doctor-backend\\pc-doctor-backend.exe" (
    start "PC Doctor Backend" /b "pc-doctor-backend\\pc-doctor-backend.exe"
) else (
    echo [ERROR] Backend executable not found at pc-doctor-backend\\pc-doctor-backend.exe
    pause
    exit /b 1
)

echo [2/3] Waiting for backend health probe on http://127.0.0.1:8765/health...
powershell -NoProfile -Command "for ($i=0; $i -lt 15; $i++) { Start-Sleep -Milliseconds 800; try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8765/health' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { Write-Host 'Backend is online!'; exit 0 } } catch {} }; exit 1"

if %errorlevel% neq 0 (
    echo [WARNING] Backend health probe did not report ready within 12s.
    echo Please verify port 8765 is not occupied.
) else (
    echo [3/3] Launching PC Doctor interface in default browser...
    start http://127.0.0.1:8765/
)

echo.
echo ========================================================
echo  PC Doctor is running at http://127.0.0.1:8765/
echo  Press any key in this window to stop PC Doctor.
echo ========================================================
pause >nul

echo Stopping PC Doctor backend...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
echo PC Doctor stopped cleanly.
"""
    (PORTABLE_DIR / "run_portable.bat").write_text(run_bat_content, encoding="utf-8")
    
    # 5. Create stop_portable.bat
    stop_bat_content = """@echo off
setlocal
echo Stopping PC Doctor processes on port 8765...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
echo PC Doctor stopped.
"""
    (PORTABLE_DIR / "stop_portable.bat").write_text(stop_bat_content, encoding="utf-8")

    # 6. Create README_PORTABLE.txt
    readme_content = """========================================================================
PC Doctor — Intelligent System Repair
Portable Desktop Distribution (v1.0.0-rc.1)
========================================================================

PC Doctor is an autonomous, cross-platform developer environment repair
and diagnosis tool featuring:
  * 75-Problem taxonomy coverage across 6 environment domains
  * Sub-second rule matching & semantic vector retrieval
  * Authoritative Safety Gate & strict Privilege Escalation Manager
  * Real-time system telemetry and environment diagnostics

------------------------------------------------------------------------
HOW TO RUN:
------------------------------------------------------------------------
1. Double-click `run_portable.bat`.
2. The bundled self-contained backend starts automatically on 127.0.0.1:8765.
3. The interface opens automatically in your default browser/webview.
4. When finished, press any key in the console window or run `stop_portable.bat`.

------------------------------------------------------------------------
REQUIREMENTS:
------------------------------------------------------------------------
* Windows 10 / 11 (x64)
* No Python installation required (self-contained bundled runtime).
* No Node.js / Vite required (pre-built production UI bundle included).
* No administrative privileges required for basic scanning and diagnosis.

------------------------------------------------------------------------
CONFIGURATION & DATA:
------------------------------------------------------------------------
* User data & runtime databases are stored in %LOCALAPPDATA%\\PC Doctor.
* Logs are stored in %LOCALAPPDATA%\\PC Doctor\\logs\\pc_doctor.log.
* AI configurations are stored in %APPDATA%\\PC Doctor\\ai_config.
========================================================================
"""
    (PORTABLE_DIR / "README_PORTABLE.txt").write_text(readme_content, encoding="utf-8")
    
    # 7. Compress into ZIP archive
    if ZIP_OUTPUT.exists():
        ZIP_OUTPUT.unlink()
        
    print(f"Creating ZIP archive: {ZIP_OUTPUT}...")
    with zipfile.ZipFile(ZIP_OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        file_count = 0
        total_size = 0
        for root, dirs, files in os.walk(PORTABLE_DIR):
            for file in files:
                abs_path = Path(root) / file
                rel_path = abs_path.relative_to(PORTABLE_DIR.parent)
                zf.write(abs_path, arcname=str(rel_path))
                file_count += 1
                total_size += abs_path.stat().st_size
                
    zip_size_mb = ZIP_OUTPUT.stat().st_size / (1024 * 1024)
    hasher = hashlib.sha256()
    with open(ZIP_OUTPUT, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    sha256_hash = hasher.hexdigest()
    
    print("=" * 60)
    print("PORTABLE PACKAGE CREATED SUCCESSFULLY!")
    print(f"Archive:       {ZIP_OUTPUT.name}")
    print(f"Path:          {ZIP_OUTPUT}")
    print(f"Files bundled: {file_count}")
    print(f"Size:          {zip_size_mb:.2f} MB")
    print(f"SHA-256:       {sha256_hash}")
    print("=" * 60)
    return sha256_hash, zip_size_mb

if __name__ == "__main__":
    assemble_portable()
