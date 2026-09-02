@echo off
title DevEngine ? DevTools Store & Control Center
echo.
echo  ????????????????????????????????????????????
echo  ?   DevEngine ? DevTools & Control Center  ?
echo  ????????????????????????????????????????????
echo.

:: Check if Python is available
where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set PYTHON=py
    goto :run
)
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set PYTHON=python
    goto :run
)
where python3 >nul 2>&1
if %ERRORLEVEL% equ 0 (
    set PYTHON=python3
    goto :run
)

echo  [ERROR] Python is not installed or not on PATH.
echo  Download it at: https://www.python.org/downloads/
echo  Remember to check "Add Python to PATH" during installation.
pause
exit /b 1

:run
echo  [INFO] Using Python: %PYTHON%
echo.

:: Install/verify dependencies quietly
echo  [INFO] Checking dependencies...
%PYTHON% -m pip install -q fastapi uvicorn[standard] psutil requests pydantic httpx 2>nul
echo  [INFO] Dependencies OK.
echo.

:: Start server
echo  [INFO] Starting server at http://127.0.0.1:8790
echo  [INFO] Press Ctrl+C to stop.
echo.
%PYTHON% backend\main.py

pause
