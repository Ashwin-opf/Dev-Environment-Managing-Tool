"""
backend/elevated_worker.py — Controlled Elevated Execution Worker

Runs as an elevated child process (via ShellExecuteExW runas on Windows)
to execute validated, structured operations with least-privilege scoping.
Never executes arbitrary natural-language text.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from dev_environment_detector import EffectivePath, PathScope, is_process_elevated
from safety import SafetyLayer, is_natural_language_command
from privilege_manager import ElevationDiagnosticLogger


def write_result(result_path: str, data: dict):
    try:
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[ElevatedWorker] Failed to write result file {result_path}: {e}", file=sys.stderr)


def main():
    t_start = time.time()
    pid = os.getpid()

    parser = argparse.ArgumentParser(description="PC Doctor Elevated Execution Worker")
    parser.add_argument("--payload", required=True, help="Path to JSON payload file")
    parser.add_argument("--result", required=True, help="Path to JSON output result file")
    parser.add_argument("--heartbeat", required=False, default=None, help="Path to heartbeat marker file")
    parser.add_argument("--desktop-launcher", action="store_true", help="Launch elevated worker via ShellExecuteExW from WinSta0\\Default")
    args = parser.parse_args()

    payload_path = args.payload
    result_path = args.result
    heartbeat_path = args.heartbeat

    # Handle desktop launcher mode: running on WinSta0\Default, invoke ShellExecuteExW(runas)
    if args.desktop_launcher:
        import ctypes
        from ctypes import wintypes

        class SHELLEXECUTEINFOW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("fMask", wintypes.ULONG),
                ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR),
                ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", ctypes.c_int),
                ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", wintypes.LPVOID),
                ("lpClass", wintypes.LPCWSTR),
                ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD),
                ("hIconOrMonitor", wintypes.HANDLE),
                ("hProcess", wintypes.HANDLE),
            ]

        ctypes.windll.ole32.CoInitializeEx(None, 0x2 | 0x4)

        sei = SHELLEXECUTEINFOW()
        sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
        sei.fMask = 0x00000040 | 0x00800000  # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOZONECHECKS
        sei.hwnd = 0
        sei.lpVerb = "runas"
        sei.lpFile = sys.executable
        sei.lpParameters = f'"{os.path.abspath(__file__)}" --payload "{payload_path}" --result "{result_path}"' + (f' --heartbeat "{heartbeat_path}"' if heartbeat_path else "")
        sei.lpDirectory = os.path.dirname(os.path.abspath(__file__))
        sei.nShow = 0

        ret = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))
        err = ctypes.GetLastError()
        if not ret or not sei.hProcess:
            sys.exit(err or 1)

        ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, 120000)
        exit_code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(sei.hProcess)
        sys.exit(exit_code.value)

    ElevationDiagnosticLogger.log("WORKER_LAUNCH_CONFIRMED", pid=pid, state="LAUNCHED")

    # Signal immediate startup if heartbeat file path was provided
    if heartbeat_path:
        try:
            with open(heartbeat_path, "w", encoding="utf-8") as hf:
                hf.write(f"STARTED:{pid}:{time.time()}\n")
            ElevationDiagnosticLogger.log("HEARTBEAT_DETECTED", pid=pid, state="HEARTBEAT_WRITTEN")
        except Exception as e:
            ElevationDiagnosticLogger.log("HEARTBEAT_DETECTED", pid=pid, state="HEARTBEAT_ERROR", details={"error": str(e)})

    if not os.path.exists(payload_path):
        write_result(result_path, {
            "status": "ELEVATED_OPERATION_FAILED",
            "exit_code": 1,
            "error": f"Payload file not found: {payload_path}",
        })
        ElevationDiagnosticLogger.log("RESULT_FILE_CREATED", pid=pid, state="FAILED_NO_PAYLOAD", error_code=1)
        sys.exit(1)

    try:
        with open(payload_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        ElevationDiagnosticLogger.log("PAYLOAD_READ", pid=pid, state="PAYLOAD_PARSED", details={"op": payload.get("operation")})
    except Exception as e:
        write_result(result_path, {
            "status": "ELEVATED_OPERATION_FAILED",
            "exit_code": 1,
            "error": f"Failed to parse payload JSON: {e}",
        })
        ElevationDiagnosticLogger.log("RESULT_FILE_CREATED", pid=pid, state="FAILED_PARSE_PAYLOAD", error_code=1)
        sys.exit(1)

    operation = payload.get("operation")
    elevated = is_process_elevated()
    app_name = payload.get("application", "System Tool")

    ElevationDiagnosticLogger.log("WORKER_VALIDATION_STARTED", pid=pid, application=app_name, state="VALIDATING", details={"op": operation, "elevated": elevated})

    # 1. Safe Admin-only Read Probe (TEST 1)
    if operation in ("ADMIN_PROBE", "TEST_ELEVATION"):
        ElevationDiagnosticLogger.log("WORKER_VALIDATION_PASSED", pid=pid, application=app_name, state="PROBE_VALID")
        ElevationDiagnosticLogger.log("WORKER_OPERATION_STARTED", pid=pid, application=app_name, state="PROBE_RUNNING")
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment", 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, "Path")
            ElevationDiagnosticLogger.log("WORKER_OPERATION_COMPLETED", pid=pid, application=app_name, state="PROBE_OK", elapsed_ms=(time.time()-t_start)*1000)
            write_result(result_path, {
                "status": "EXECUTED",
                "operation": operation,
                "is_elevated": elevated,
                "exit_code": 0,
                "message": "Elevation probe succeeded: successfully read Machine Environment registry.",
                "path_length": len(val),
            })
            ElevationDiagnosticLogger.log("RESULT_FILE_CREATED", pid=pid, application=app_name, state="RESULT_WRITTEN", error_code=0)
            sys.exit(0)
        except Exception as e:
            ElevationDiagnosticLogger.log("WORKER_OPERATION_COMPLETED", pid=pid, application=app_name, state="PROBE_FAILED", error_code=1, details={"error": str(e)})
            write_result(result_path, {
                "status": "ELEVATED_OPERATION_FAILED",
                "operation": operation,
                "is_elevated": elevated,
                "exit_code": 1,
                "error": f"Admin probe read failed: {e}",
            })
            ElevationDiagnosticLogger.log("RESULT_FILE_CREATED", pid=pid, application=app_name, state="RESULT_WRITTEN", error_code=1)
            sys.exit(1)

    # 2. Structured PATH Repair (TESTS 2, 4, 5)
    if operation == "REPAIR_PATH":
        directory = payload.get("directory")
        scope = (payload.get("scope") or "MACHINE").upper()

        if not directory:
            write_result(result_path, {
                "status": "ELEVATED_OPERATION_FAILED",
                "operation": "REPAIR_PATH",
                "exit_code": 1,
                "error": "Missing target directory in REPAIR_PATH operation",
            })
            ElevationDiagnosticLogger.log("RESULT_FILE_CREATED", pid=pid, application=app_name, state="MISSING_DIRECTORY", error_code=1)
            sys.exit(1)

        clean_dir = os.path.normpath(os.path.expandvars(os.path.expanduser(str(directory).strip().strip('"').strip("'"))))
        if not os.path.isdir(clean_dir):
            write_result(result_path, {
                "status": "ELEVATED_OPERATION_FAILED",
                "operation": "REPAIR_PATH",
                "exit_code": 1,
                "error": f"Target directory does not exist on disk: {clean_dir}",
            })
            ElevationDiagnosticLogger.log("RESULT_FILE_CREATED", pid=pid, application=app_name, state="DIR_NOT_FOUND", error_code=1)
            sys.exit(1)

        ElevationDiagnosticLogger.log("WORKER_VALIDATION_PASSED", pid=pid, application=app_name, state="REPAIR_VALID", details={"dir": clean_dir, "scope": scope})
        ElevationDiagnosticLogger.log("WORKER_OPERATION_STARTED", pid=pid, application=app_name, state="REPAIR_RUNNING")

        path_scope = PathScope.MACHINE if scope == "MACHINE" else PathScope.USER
        ok, msg = EffectivePath.add_to_persistent_path(clean_dir, scope=path_scope, elevate_if_needed=False)

        ElevationDiagnosticLogger.log("WORKER_OPERATION_COMPLETED", pid=pid, application=app_name, state="REPAIR_DONE" if ok else "REPAIR_FAILED", error_code=0 if ok else 1, elapsed_ms=(time.time()-t_start)*1000)

        write_result(result_path, {
            "status": "EXECUTED" if ok else "ELEVATED_OPERATION_FAILED",
            "operation": "REPAIR_PATH",
            "scope": scope,
            "application": app_name,
            "directory": clean_dir,
            "is_elevated": elevated,
            "exit_code": 0 if ok else 1,
            "message": msg,
        })
        ElevationDiagnosticLogger.log("RESULT_FILE_CREATED", pid=pid, application=app_name, state="RESULT_WRITTEN", error_code=0 if ok else 1)
        sys.exit(0 if ok else 1)

    # 2b. Structured PATH Removal (Test Lab)
    if operation == "REMOVE_PATH":
        directory = payload.get("directory")
        scope = (payload.get("scope") or "MACHINE").upper()
        clean_dir = os.path.normpath(os.path.expandvars(os.path.expanduser(str(directory).strip().strip('"').strip("'"))))
        path_scope = PathScope.MACHINE if scope == "MACHINE" else PathScope.USER

        ElevationDiagnosticLogger.log("WORKER_OPERATION_STARTED", pid=pid, application=app_name, state="REMOVE_PATH_RUNNING", details={"dir": clean_dir, "scope": scope})
        ok, msg = EffectivePath.remove_from_persistent_path(clean_dir, scope=path_scope)
        ElevationDiagnosticLogger.log("WORKER_OPERATION_COMPLETED", pid=pid, application=app_name, state="REMOVE_PATH_DONE" if ok else "REMOVE_PATH_FAILED", error_code=0 if ok else 1)

        write_result(result_path, {
            "status": "EXECUTED" if ok else "ELEVATED_OPERATION_FAILED",
            "operation": "REMOVE_PATH",
            "scope": scope,
            "application": app_name,
            "directory": clean_dir,
            "is_elevated": elevated,
            "exit_code": 0 if ok else 1,
            "message": msg,
        })
        sys.exit(0 if ok else 1)

    # 2c. Structured PATH Exact Restoration (Test Lab)
    if operation == "RESTORE_PATH":
        exact_path = payload.get("path", "")
        scope = (payload.get("scope") or "MACHINE").upper()
        path_scope = PathScope.MACHINE if scope == "MACHINE" else PathScope.USER

        ElevationDiagnosticLogger.log("WORKER_OPERATION_STARTED", pid=pid, application=app_name, state="RESTORE_PATH_RUNNING", details={"scope": scope})
        ok, msg = EffectivePath.set_exact_persistent_path(exact_path, scope=path_scope)
        ElevationDiagnosticLogger.log("WORKER_OPERATION_COMPLETED", pid=pid, application=app_name, state="RESTORE_PATH_DONE" if ok else "RESTORE_PATH_FAILED", error_code=0 if ok else 1)

        write_result(result_path, {
            "status": "EXECUTED" if ok else "ELEVATED_OPERATION_FAILED",
            "operation": "RESTORE_PATH",
            "scope": scope,
            "application": app_name,
            "is_elevated": elevated,
            "exit_code": 0 if ok else 1,
            "message": msg,
        })
        sys.exit(0 if ok else 1)

    # 3. Validated Command Fallback
    if operation == "EXECUTE_COMMAND":
        cmd = payload.get("command", "")
        clean_cmd = (cmd or "").strip()

        if not clean_cmd or clean_cmd.startswith("#") or is_natural_language_command(clean_cmd):
            write_result(result_path, {
                "status": "ELEVATED_OPERATION_FAILED",
                "exit_code": 1,
                "error": "Execution rejected: command is empty, a comment, or natural language.",
            })
            ElevationDiagnosticLogger.log("RESULT_FILE_CREATED", pid=pid, application=app_name, state="NL_REJECTED", error_code=1)
            sys.exit(1)

        safety = SafetyLayer()
        blocked, block_reason = safety.validate(clean_cmd)
        if blocked:
            write_result(result_path, {
                "status": "ELEVATED_OPERATION_FAILED",
                "exit_code": 1,
                "error": f"Execution rejected by Safety Layer: {block_reason}",
            })
            ElevationDiagnosticLogger.log("RESULT_FILE_CREATED", pid=pid, application=app_name, state="SAFETY_REJECTED", error_code=1)
            sys.exit(1)

        ElevationDiagnosticLogger.log("WORKER_VALIDATION_PASSED", pid=pid, application=app_name, state="CMD_VALID")
        ElevationDiagnosticLogger.log("WORKER_OPERATION_STARTED", pid=pid, application=app_name, state="CMD_RUNNING")

        import subprocess
        proc = subprocess.run(clean_cmd, shell=True, text=True, capture_output=True)
        ElevationDiagnosticLogger.log("WORKER_OPERATION_COMPLETED", pid=pid, application=app_name, state="CMD_COMPLETED", error_code=proc.returncode, elapsed_ms=(time.time()-t_start)*1000)

        write_result(result_path, {
            "status": "EXECUTED" if proc.returncode == 0 else "ELEVATED_OPERATION_FAILED",
            "operation": "EXECUTE_COMMAND",
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "is_elevated": elevated,
        })
        ElevationDiagnosticLogger.log("RESULT_FILE_CREATED", pid=pid, application=app_name, state="RESULT_WRITTEN", error_code=proc.returncode)
        sys.exit(proc.returncode)

    # Unknown operation
    write_result(result_path, {
        "status": "ELEVATED_OPERATION_FAILED",
        "exit_code": 1,
        "error": f"Unknown elevated operation: {operation}",
    })
    ElevationDiagnosticLogger.log("RESULT_FILE_CREATED", pid=pid, application=app_name, state="UNKNOWN_OP", error_code=1)
    sys.exit(1)


if __name__ == "__main__":
    main()
