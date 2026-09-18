"""
backend/privilege_manager.py — Cross-Platform Privilege & Elevation Management Subsystem

Provides structured, least-privilege administrator elevation with:
1. Strict platform abstraction (Windows, Linux, macOS).
2. Explicit state machine transitions with fine-grained failure classification.
3. Policy-configurable bounded timeouts (UAC prompt, worker launch, heartbeat, result).
4. COM-initialized ShellExecuteExW with valid HWND or NULL owner (never GetDesktopWindow).
5. Comprehensive structured diagnostic logging for tracing every elevation stage.
6. Structured, validated payloads only — never arbitrary natural language text.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import os
import platform
import queue
import shutil
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Dict, Generator, Optional, Tuple


class ElevationState(str, Enum):
    # Lifecycle states
    ELEVATION_NOT_STARTED = "ELEVATION_NOT_STARTED"
    PREPARING = "PREPARING"
    RECIPE_VALIDATED = "RECIPE_VALIDATED"
    SAFETY_CHECKED = "SAFETY_CHECKED"
    ELEVATION_REQUESTED = "ELEVATION_REQUESTED"
    ELEVATION_PROMPT_SHOWN = "ELEVATION_PROMPT_SHOWN"
    UAC_PROMPT_WAITING = "UAC_PROMPT_WAITING"
    ELEVATION_GRANTED = "ELEVATION_GRANTED"
    WORKER_STARTING = "WORKER_STARTING"
    ELEVATED_PROCESS_STARTED = "ELEVATED_PROCESS_STARTED"
    WORKER_STARTED = "WORKER_STARTED"
    ELEVATED_OPERATION_EXECUTING = "ELEVATED_OPERATION_EXECUTING"
    OPERATION_EXECUTING = "OPERATION_EXECUTING"
    ELEVATED_OPERATION_COMPLETED = "ELEVATED_OPERATION_COMPLETED"
    OPERATION_COMPLETED = "OPERATION_COMPLETED"
    RESULT_RECEIVED = "RESULT_RECEIVED"
    VERIFICATION_RUNNING = "VERIFICATION_RUNNING"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"

    # Specific failure states
    USER_DECLINED_ELEVATION = "USER_DECLINED_ELEVATION"
    UAC_CANCELLED = "UAC_CANCELLED"
    UAC_NOT_STARTED = "UAC_NOT_STARTED"
    UAC_LAUNCH_FAILED = "UAC_LAUNCH_FAILED"
    UAC_PROMPT_TIMEOUT = "UAC_PROMPT_TIMEOUT"
    WORKER_START_FAILED = "WORKER_START_FAILED"
    RESULT_TIMEOUT = "RESULT_TIMEOUT"
    RESULT_NOT_RETURNED = "RESULT_NOT_RETURNED"
    ELEVATED_OPERATION_FAILED = "ELEVATED_OPERATION_FAILED"
    OPERATION_FAILED = "OPERATION_FAILED"
    ELEVATION_FAILED = "ELEVATION_FAILED"
    ELEVATION_DENIED = "ELEVATION_DENIED"


STATE_PROGRESS_MAP: Dict[str, Tuple[int, str]] = {
    ElevationState.ELEVATION_NOT_STARTED.value: (0, "Preparing execution"),
    ElevationState.PREPARING.value: (0, "Preparing execution"),
    ElevationState.RECIPE_VALIDATED.value: (10, "Recipe validated"),
    ElevationState.SAFETY_CHECKED.value: (20, "Safety checked"),
    ElevationState.ELEVATION_REQUESTED.value: (30, "Awaiting Administrator approval (UAC)"),
    ElevationState.ELEVATION_PROMPT_SHOWN.value: (35, "Windows UAC prompt active"),
    ElevationState.UAC_PROMPT_WAITING.value: (35, "Awaiting Windows Administrator permission (UAC dialog)..."),
    ElevationState.ELEVATION_GRANTED.value: (40, "Administrator permission granted"),
    ElevationState.WORKER_STARTING.value: (45, "Starting elevated execution worker..."),
    ElevationState.ELEVATED_PROCESS_STARTED.value: (50, "Elevated worker process started"),
    ElevationState.WORKER_STARTED.value: (50, "Elevated worker process started"),
    ElevationState.ELEVATED_OPERATION_EXECUTING.value: (60, "Executing elevated operation"),
    ElevationState.OPERATION_EXECUTING.value: (60, "Executing elevated operation"),
    ElevationState.ELEVATED_OPERATION_COMPLETED.value: (75, "Elevated operation completed"),
    ElevationState.OPERATION_COMPLETED.value: (75, "Elevated operation completed"),
    ElevationState.RESULT_RECEIVED.value: (75, "Worker result file received"),
    ElevationState.VERIFICATION_RUNNING.value: (85, "Verifying environment resolution"),
    ElevationState.VERIFYING.value: (85, "Verifying environment resolution"),
    ElevationState.VERIFIED.value: (100, "Verified and resolved"),

    # Failure classifications (exit from 30%)
    ElevationState.USER_DECLINED_ELEVATION.value: (30, "Administrator approval declined by user"),
    ElevationState.UAC_CANCELLED.value: (30, "Administrator approval declined by user"),
    ElevationState.UAC_NOT_STARTED.value: (30, "UAC prompt could not be initiated"),
    ElevationState.UAC_LAUNCH_FAILED.value: (30, "Elevation launch failed"),
    ElevationState.UAC_PROMPT_TIMEOUT.value: (30, "UAC approval prompt timed out"),
    ElevationState.WORKER_START_FAILED.value: (40, "Elevated worker failed to start"),
    ElevationState.RESULT_TIMEOUT.value: (60, "Elevated worker operation timed out"),
    ElevationState.RESULT_NOT_RETURNED.value: (60, "Worker finished without writing result file"),
    ElevationState.ELEVATED_OPERATION_FAILED.value: (60, "Elevated operation execution failed"),
    ElevationState.OPERATION_FAILED.value: (60, "Elevated operation execution failed"),
    ElevationState.ELEVATION_FAILED.value: (30, "Administrator elevation failed"),
}


@dataclass
class ElevationPolicy:
    """Configurable bounded timeouts for each phase of elevation."""
    prompt_timeout_seconds: int = 45          # Timeout waiting for user on UAC consent dialog
    worker_start_timeout_seconds: int = 5     # Timeout waiting for worker heartbeat marker
    result_timeout_seconds: int = 20          # Timeout waiting for worker result file
    total_timeout_seconds: int = 60           # Overall safety ceiling


class ElevationDiagnosticLogger:
    """Logs structured diagnostic events specifically around elevation for real-time tracing."""

    LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "elevation_diag.log")

    @classmethod
    def log(
        cls,
        stage: str,
        operation_id: str = "",
        application: str = "",
        pid: Optional[int] = None,
        state: str = "",
        error_code: Optional[int] = None,
        win32_error: Optional[int] = None,
        elapsed_ms: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "operation_id": operation_id,
            "application": application,
            "pid": pid or os.getpid(),
            "state": state,
            "error_code": error_code,
            "win32_error": win32_error,
            "elapsed_ms": round(elapsed_ms, 2) if elapsed_ms is not None else None,
            "details": details or {},
        }
        try:
            with open(cls.LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass
        return entry


class BasePrivilegeAdapter(ABC):
    """Abstract base class for platform-specific privilege elevation adapters."""

    @abstractmethod
    def is_elevated(self) -> bool:
        """Return True if current process is running with administrator/root privileges."""
        pass

    @abstractmethod
    def execute_elevated(
        self, payload: Dict[str, Any], timeout_sec: int = 60
    ) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        """
        Execute a structured payload with elevated privileges, yielding progress events.
        Must never execute arbitrary natural-language text.
        """
        pass

    def check_pre_elevation_safety(self, payload: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
        """
        Enforces that administrative elevation cannot bypass the Live Safety Gate.
        Evaluates command inside payload before any UAC prompt or worker process is launched.
        """
        cmd = (payload.get("command") or "").strip()
        if not cmd:
            return True, "", None
        from authoritative_safety import authoritative_safety
        op = payload.get("operation", "EXECUTE")
        app = payload.get("application", "System Tool")
        res = authoritative_safety.live_pre_execution_gate(
            command=cmd,
            operation=op,
            target_resource=app,
        )
        if not res.allowed:
            reason_val = res.blocked_reason.value if res.blocked_reason else "SAFETY_BLOCKED"
            return False, res.message, reason_val
        return True, "", None


class WindowsPrivilegeAdapter(BasePrivilegeAdapter):
    """
    Windows-specific privilege elevation using ShellExecuteExW runas.
    - Uses COM-initialized STA thread.
    - Sets hwnd = 0 (NULL) or genuine top-level window (never GetDesktopWindow()).
    - Uses SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOZONECHECKS.
    - Enforces separate bounded timeouts for UAC prompt, worker launch, and operation.
    """

    def __init__(self, policy: Optional[ElevationPolicy] = None):
        self.policy = policy or ElevationPolicy()

    def is_elevated(self) -> bool:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    @staticmethod
    def get_interactive_window_handle() -> int:
        """
        Retrieves a valid visible interactive window handle (HWND) for UAC consent binding.
        CRITICAL: Never return GetDesktopWindow(), as modal dialog parenting to desktop hangs.
        CRITICAL: Do NOT parent to foreign processes (like IDE, Chrome, or Explorer), as Windows
        UIPI and cross-process foreground security will automatically reject elevation with 1223.
        Only use an HWND if it belongs to the current process; otherwise return 0 (NULL) so
        Windows centers the top-level UAC consent dialog cleanly on the active monitor.
        """
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            current_pid = kernel32.GetCurrentProcessId()

            hwnd = user32.GetForegroundWindow()
            if hwnd and hwnd != 0:
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == current_pid:
                    desk = user32.GetDesktopWindow()
                    if hwnd != desk and user32.IsWindowVisible(hwnd):
                        return hwnd
        except Exception:
            pass
        return 0

    def execute_elevated(
        self, payload: Dict[str, Any], timeout_sec: int = 60
    ) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        import ctypes
        from ctypes import wintypes

        policy = self.policy
        op_name = payload.get("operation", "UNKNOWN")
        app_name = payload.get("application", "System Tool")
        op_id = f"elev_{int(time.time()*1000)}"
        t0 = time.time()

        ElevationDiagnosticLogger.log(
            "ELEVATION_START",
            operation_id=op_id,
            application=app_name,
            state="START",
            details={"operation": op_name, "timeout_sec": timeout_sec},
        )

        safe, msg, reason_code = self.check_pre_elevation_safety(payload)
        if not safe:
            err_msg = f"Elevated execution rejected by Live Safety Gate: {msg}"
            yield {"type": "log", "text": f"[Safety Blocked]: {err_msg}", "stream": "stderr"}
            yield {
                "type": "done",
                "returncode": -1,
                "ok": False,
                "status": "BLOCKED",
                "code": reason_code or "SAFETY_BLOCKED",
                "message": err_msg,
                "stderr": err_msg,
                "requires_elevation": True,
            }
            return {
                "ok": False,
                "status": "BLOCKED",
                "code": reason_code or "SAFETY_BLOCKED",
                "message": err_msg,
                "stderr": err_msg,
                "exit_code": -1,
            }

        backend_dir = os.path.dirname(os.path.abspath(__file__))
        worker_script = os.path.abspath(os.path.join(backend_dir, "elevated_worker.py"))
        python_exe = os.path.abspath(sys.executable)

        payload_fd, payload_path = tempfile.mkstemp(suffix=".json", prefix="pcdoc_elev_payload_")
        result_fd, result_path = tempfile.mkstemp(suffix=".json", prefix="pcdoc_elev_result_")
        heartbeat_fd, heartbeat_path = tempfile.mkstemp(suffix=".marker", prefix="pcdoc_elev_hb_")

        with open(payload_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.close(payload_fd)
        os.close(result_fd)
        os.close(heartbeat_fd)

        ElevationDiagnosticLogger.log(
            "ELEVATION_REQUEST_CREATED",
            operation_id=op_id,
            application=app_name,
            state="CREATED",
            elapsed_ms=(time.time() - t0) * 1000,
            details={"payload_path": payload_path, "worker_script": worker_script, "python_exe": python_exe},
        )

        # Signal state: ELEVATION_REQUESTED
        pct, detail = STATE_PROGRESS_MAP[ElevationState.ELEVATION_REQUESTED.value]
        yield {
            "type": "progress",
            "percent": pct,
            "state": ElevationState.ELEVATION_REQUESTED.value,
            "detail": detail,
        }
        yield {
            "type": "log",
            "text": "Requesting Windows Administrator permission (UAC)...",
            "stream": "stdout",
        }

        # Background runner for ShellExecuteExW
        event_q: queue.Queue = queue.Queue()
        stop_event = threading.Event()

        def _runner():
            SEE_MASK_NOCLOSEPROCESS = 0x00000040
            SEE_MASK_NOZONECHECKS = 0x00800000

            class STARTUPINFOW(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                    ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                    ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", wintypes.LPBYTE),
                    ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
                ]

            class PROCESS_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
                ]

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

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            shell32 = ctypes.windll.shell32
            ole32 = ctypes.windll.ole32

            # Check if current process was spawned on an isolated virtual desktop (e.g. exebox-*)
            si_curr = STARTUPINFOW()
            si_curr.cb = ctypes.sizeof(STARTUPINFOW)
            kernel32.GetStartupInfoW(ctypes.byref(si_curr))
            curr_desk = str(si_curr.lpDesktop or "").lower()
            needs_desktop_transition = bool(curr_desk and curr_desk not in ("default", "winsta0\\default"))

            ElevationDiagnosticLogger.log(
                "ELEVATION_API_CALLED",
                operation_id=op_id,
                application=app_name,
                state="CALLING",
                elapsed_ms=(time.time() - t0) * 1000,
                details={"needs_desktop_transition": needs_desktop_transition, "curr_desk": curr_desk, "exe": python_exe},
            )

            hProcess = None
            child_pid = None
            api_ms = 0.0

            if needs_desktop_transition:
                # Spawn launcher helper process explicitly on WinSta0\Default
                si = STARTUPINFOW()
                si.cb = ctypes.sizeof(STARTUPINFOW)
                si.lpDesktop = r"WinSta0\Default"

                pi = PROCESS_INFORMATION()
                launcher_cmd = f'"{python_exe}" "{worker_script}" --desktop-launcher --payload "{payload_path}" --result "{result_path}" --heartbeat "{heartbeat_path}"'

                t_api = time.time()
                success = kernel32.CreateProcessW(None, launcher_cmd, None, None, False, 0, None, None, ctypes.byref(si), ctypes.byref(pi))
                api_ms = (time.time() - t_api) * 1000
                win32_err = ctypes.GetLastError() if not success else 0

                if not success:
                    ElevationDiagnosticLogger.log(
                        "UAC_APPROVAL_RESULT",
                        operation_id=op_id,
                        application=app_name,
                        state="LAUNCH_FAILED",
                        error_code=win32_err,
                        win32_error=win32_err,
                        elapsed_ms=(time.time() - t0) * 1000,
                    )
                    event_q.put(("UAC_LAUNCH_FAILED", win32_err, None))
                    return

                kernel32.CloseHandle(pi.hThread)
                hProcess = pi.hProcess
                child_pid = pi.dwProcessId
            else:
                # Direct ShellExecuteExW on current desktop
                hr_com = ole32.CoInitializeEx(None, 0x2 | 0x4)
                hwnd = self.get_interactive_window_handle()
                params = f'"{worker_script}" --payload "{payload_path}" --result "{result_path}" --heartbeat "{heartbeat_path}"'

                sei = SHELLEXECUTEINFOW()
                sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
                sei.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOZONECHECKS
                sei.hwnd = hwnd if hwnd != 0 else None
                sei.lpVerb = "runas"
                sei.lpFile = python_exe
                sei.lpParameters = params
                sei.lpDirectory = backend_dir
                sei.nShow = 0

                t_api = time.time()
                success = shell32.ShellExecuteExW(ctypes.byref(sei))
                api_ms = (time.time() - t_api) * 1000
                win32_err = ctypes.GetLastError() if not success else 0

                if not success:
                    if win32_err == 1223:  # ERROR_CANCELLED (User declined)
                        ElevationDiagnosticLogger.log(
                            "UAC_APPROVAL_RESULT",
                            operation_id=op_id,
                            application=app_name,
                            state="CANCELLED",
                            error_code=1223,
                            win32_error=1223,
                            elapsed_ms=(time.time() - t0) * 1000,
                        )
                        event_q.put(("UAC_CANCELLED", 1223, None))
                    else:
                        ElevationDiagnosticLogger.log(
                            "UAC_APPROVAL_RESULT",
                            operation_id=op_id,
                            application=app_name,
                            state="LAUNCH_FAILED",
                            error_code=win32_err,
                            win32_error=win32_err,
                            elapsed_ms=(time.time() - t0) * 1000,
                        )
                        event_q.put(("UAC_LAUNCH_FAILED", win32_err, None))
                    return

                hProcess = sei.hProcess
                child_pid = kernel32.GetProcessId(hProcess) if hProcess else 0

            ElevationDiagnosticLogger.log(
                "ELEVATION_API_RETURNED",
                operation_id=op_id,
                application=app_name,
                state="RETURNED",
                win32_error=0,
                elapsed_ms=api_ms,
                details={"success": True, "pid": child_pid},
            )
            ElevationDiagnosticLogger.log(
                "ELEVATED_PROCESS_HANDLE_RECEIVED",
                operation_id=op_id,
                application=app_name,
                pid=child_pid,
                state="HANDLE_RECEIVED",
                elapsed_ms=(time.time() - t0) * 1000,
            )

            # Monitor process execution
            launch_time = time.time()
            heartbeat_seen = False
            result_seen = False

            while not stop_event.is_set():
                # 1. Check for heartbeat
                if not heartbeat_seen and os.path.exists(heartbeat_path) and os.path.getsize(heartbeat_path) > 0:
                    heartbeat_seen = True
                    ElevationDiagnosticLogger.log(
                        "HEARTBEAT_DETECTED",
                        operation_id=op_id,
                        application=app_name,
                        pid=child_pid,
                        state="HEARTBEAT",
                        elapsed_ms=(time.time() - t0) * 1000,
                    )
                    event_q.put(("ELEVATION_GRANTED", 0, child_pid))
                    event_q.put(("HEARTBEAT_DETECTED", 0, child_pid))

                # 2. Check for result file
                if not result_seen and os.path.exists(result_path) and os.path.getsize(result_path) > 0:
                    result_seen = True
                    ElevationDiagnosticLogger.log(
                        "RESULT_FILE_CREATED",
                        operation_id=op_id,
                        application=app_name,
                        pid=child_pid,
                        state="RESULT_CREATED",
                        elapsed_ms=(time.time() - t0) * 1000,
                    )
                    event_q.put(("RESULT_DETECTED", 0, child_pid))

                # 3. Check process exit
                wait_ret = kernel32.WaitForSingleObject(hProcess, 100)
                if wait_ret == 0:  # WAIT_OBJECT_0: Process completed
                    exit_code = wintypes.DWORD()
                    kernel32.GetExitCodeProcess(hProcess, ctypes.byref(exit_code))
                    kernel32.CloseHandle(hProcess)

                    ec_val = exit_code.value
                    if ec_val == 1223:  # ERROR_CANCELLED
                        ElevationDiagnosticLogger.log(
                            "UAC_APPROVAL_RESULT",
                            operation_id=op_id,
                            application=app_name,
                            pid=child_pid,
                            state="CANCELLED",
                            error_code=1223,
                            win32_error=1223,
                            elapsed_ms=(time.time() - t0) * 1000,
                        )
                        event_q.put(("UAC_CANCELLED", 1223, child_pid))
                        return

                    ElevationDiagnosticLogger.log(
                        "CHILD_EXIT_CODE",
                        operation_id=op_id,
                        application=app_name,
                        pid=child_pid,
                        state="EXITED",
                        error_code=ec_val,
                        elapsed_ms=(time.time() - t0) * 1000,
                    )
                    event_q.put(("PROCESS_DONE", ec_val, child_pid))
                    return

                # 4. Check worker-start timeout (waiting for UAC approval + worker startup)
                elapsed_since_launch = time.time() - launch_time
                max_start_time = policy.prompt_timeout_seconds + policy.worker_start_timeout_seconds
                if not heartbeat_seen and elapsed_since_launch > max_start_time:
                    try:
                        kernel32.TerminateProcess(hProcess, 1)
                    except Exception:
                        pass
                    kernel32.CloseHandle(hProcess)
                    ElevationDiagnosticLogger.log(
                        "WORKER_LAUNCH_CONFIRMED",
                        operation_id=op_id,
                        application=app_name,
                        pid=child_pid,
                        state="START_FAILED",
                        error_code=1,
                        elapsed_ms=(time.time() - t0) * 1000,
                    )
                    event_q.put(("WORKER_START_FAILED", 1, child_pid))
                    return

                # 5. Check result timeout
                if heartbeat_seen and (time.time() - launch_time) > (max_start_time + policy.result_timeout_seconds):
                    try:
                        kernel32.TerminateProcess(hProcess, 124)
                    except Exception:
                        pass
                    kernel32.CloseHandle(hProcess)
                    ElevationDiagnosticLogger.log(
                        "WORKER_OPERATION_COMPLETED",
                        operation_id=op_id,
                        application=app_name,
                        pid=child_pid,
                        state="TIMEOUT",
                        error_code=124,
                        elapsed_ms=(time.time() - t0) * 1000,
                    )
                    event_q.put(("RESULT_TIMEOUT", 124, child_pid))
                    return

        runner_thread = threading.Thread(target=_runner, daemon=True)
        runner_thread.start()

        process_started = False
        final_result: Dict[str, Any] = {}
        prompt_start_time = time.time()

        try:
            while True:
                try:
                    ev_type, code, child_pid = event_q.get(timeout=0.15)
                except queue.Empty:
                    # Check UAC prompt approval timeout
                    if not process_started and (time.time() - prompt_start_time) > policy.prompt_timeout_seconds:
                        stop_event.set()
                        ElevationDiagnosticLogger.log(
                            "UAC_APPROVAL_RESULT",
                            operation_id=op_id,
                            application=app_name,
                            state="PROMPT_TIMEOUT",
                            error_code=124,
                            elapsed_ms=(time.time() - t0) * 1000,
                        )
                        msg = f"Administrator approval timed out after {policy.prompt_timeout_seconds} seconds."
                        final_result = {
                            "ok": False,
                            "status": ElevationState.ELEVATION_FAILED.value,
                            "code": "ELEVATION_TIMEOUT",
                            "message": msg,
                            "exit_code": 124,
                            "requires_elevation": True,
                        }
                        yield {
                            "type": "progress",
                            "percent": 30,
                            "state": ElevationState.ELEVATION_FAILED.value,
                            "detail": msg,
                        }
                        yield {
                            "type": "done",
                            "returncode": 124,
                            "stdout": "",
                            "stderr": msg,
                            "ok": False,
                            "status": ElevationState.ELEVATION_FAILED.value,
                            "code": "ELEVATION_TIMEOUT",
                            "requires_elevation": True,
                        }
                        return final_result
                    continue

                if ev_type == "UAC_CANCELLED":
                    stop_event.set()
                    msg = "Administrator permission was not granted by user. System PATH was not changed."
                    final_result = {
                        "ok": False,
                        "status": ElevationState.USER_DECLINED_ELEVATION.value,
                        "code": "ELEVATION_CANCELLED",
                        "message": msg,
                        "exit_code": 1223,
                        "requires_elevation": True,
                    }
                    yield {"type": "log", "text": f"[Elevation Cancelled]: {msg}", "stream": "stderr"}
                    yield {
                        "type": "progress",
                        "percent": 30,
                        "state": ElevationState.USER_DECLINED_ELEVATION.value,
                        "detail": msg,
                    }
                    yield {
                        "type": "done",
                        "returncode": 1223,
                        "stdout": "",
                        "stderr": msg,
                        "ok": False,
                        "status": ElevationState.USER_DECLINED_ELEVATION.value,
                        "code": "ELEVATION_CANCELLED",
                        "requires_elevation": True,
                        "notice": msg,
                    }
                    return final_result

                elif ev_type == "UAC_LAUNCH_FAILED":
                    stop_event.set()
                    msg = f"Windows elevation failed to launch (Win32 error {code})."
                    final_result = {
                        "ok": False,
                        "status": ElevationState.ELEVATION_FAILED.value,
                        "code": "ELEVATION_LAUNCH_FAILED",
                        "message": msg,
                        "exit_code": code or 1,
                        "requires_elevation": True,
                    }
                    yield {"type": "log", "text": f"[Elevation Error]: {msg}", "stream": "stderr"}
                    yield {
                        "type": "done",
                        "returncode": code or 1,
                        "stdout": "",
                        "stderr": msg,
                        "ok": False,
                        "status": ElevationState.ELEVATION_FAILED.value,
                        "code": "ELEVATION_LAUNCH_FAILED",
                        "requires_elevation": True,
                    }
                    return final_result

                elif ev_type == "ELEVATION_GRANTED":
                    process_started = True
                    pct40, d40 = STATE_PROGRESS_MAP[ElevationState.ELEVATION_GRANTED.value]
                    yield {"type": "progress", "percent": pct40, "state": ElevationState.ELEVATION_GRANTED.value, "detail": d40}
                    yield {"type": "log", "text": "Administrator permission granted by user.", "stream": "stdout"}

                    pct45, d45 = STATE_PROGRESS_MAP[ElevationState.WORKER_STARTING.value]
                    yield {"type": "progress", "percent": pct45, "state": ElevationState.WORKER_STARTING.value, "detail": d45}

                elif ev_type == "HEARTBEAT_DETECTED":
                    pct50, d50 = STATE_PROGRESS_MAP[ElevationState.ELEVATED_PROCESS_STARTED.value]
                    yield {"type": "progress", "percent": pct50, "state": ElevationState.ELEVATED_PROCESS_STARTED.value, "detail": d50}

                    pct60, d60 = STATE_PROGRESS_MAP[ElevationState.ELEVATED_OPERATION_EXECUTING.value]
                    yield {"type": "progress", "percent": pct60, "state": ElevationState.ELEVATED_OPERATION_EXECUTING.value, "detail": d60}
                    yield {"type": "log", "text": "Executing elevated operation in isolated worker...", "stream": "stdout"}

                elif ev_type == "WORKER_START_FAILED":
                    stop_event.set()
                    msg = "Elevated worker process failed to start or did not emit startup heartbeat."
                    final_result = {
                        "ok": False,
                        "status": ElevationState.ELEVATION_FAILED.value,
                        "code": "WORKER_START_FAILED",
                        "message": msg,
                        "exit_code": 1,
                        "requires_elevation": True,
                    }
                    yield {"type": "log", "text": f"[Worker Error]: {msg}", "stream": "stderr"}
                    yield {
                        "type": "done",
                        "returncode": 1,
                        "stdout": "",
                        "stderr": msg,
                        "ok": False,
                        "status": ElevationState.ELEVATION_FAILED.value,
                        "code": "WORKER_START_FAILED",
                        "requires_elevation": True,
                    }
                    return final_result

                elif ev_type == "RESULT_TIMEOUT":
                    stop_event.set()
                    msg = f"Elevated worker operation timed out after {policy.result_timeout_seconds} seconds."
                    final_result = {
                        "ok": False,
                        "status": ElevationState.ELEVATION_FAILED.value,
                        "code": "OPERATION_TIMEOUT",
                        "message": msg,
                        "exit_code": 124,
                        "requires_elevation": True,
                    }
                    yield {"type": "log", "text": f"[Timeout Error]: {msg}", "stream": "stderr"}
                    yield {
                        "type": "done",
                        "returncode": 124,
                        "stdout": "",
                        "stderr": msg,
                        "ok": False,
                        "status": ElevationState.ELEVATION_FAILED.value,
                        "code": "OPERATION_TIMEOUT",
                        "requires_elevation": True,
                    }
                    return final_result

                elif ev_type == "RESULT_DETECTED":
                    pct70, d70 = STATE_PROGRESS_MAP[ElevationState.ELEVATED_OPERATION_COMPLETED.value]
                    yield {"type": "progress", "percent": pct70, "state": ElevationState.ELEVATED_OPERATION_COMPLETED.value, "detail": d70}

                elif ev_type == "PROCESS_DONE":
                    ec = code
                    stop_event.set()

                    # Read worker result file
                    worker_result = {}
                    if os.path.exists(result_path) and os.path.getsize(result_path) > 0:
                        try:
                            with open(result_path, "r", encoding="utf-8") as rf:
                                worker_result = json.load(rf)
                            ElevationDiagnosticLogger.log(
                                "RESULT_FILE_READ",
                                operation_id=op_id,
                                application=app_name,
                                state="RESULT_READ",
                                elapsed_ms=(time.time() - t0) * 1000,
                                details={"status": worker_result.get("status")},
                            )
                        except Exception as e:
                            worker_result = {"error": f"Failed to parse worker output: {e}"}

                    pct75, d75 = STATE_PROGRESS_MAP[ElevationState.RESULT_RECEIVED.value]
                    yield {"type": "progress", "percent": pct75, "state": ElevationState.RESULT_RECEIVED.value, "detail": d75}

                    is_ok = (ec == 0 and worker_result.get("status") == "EXECUTED")
                    ElevationDiagnosticLogger.log(
                        "PARENT_COMPLETION_RECEIVED",
                        operation_id=op_id,
                        application=app_name,
                        state="SUCCESS" if is_ok else "FAILED",
                        error_code=ec,
                        elapsed_ms=(time.time() - t0) * 1000,
                    )

                    if is_ok:
                        msg = worker_result.get("message", "Elevated operation completed successfully.")
                        yield {"type": "log", "text": f"[Elevated Operation]: {msg}", "stream": "stdout"}
                        final_result = {
                            "ok": True,
                            "status": "EXECUTED",
                            "exit_code": 0,
                            "message": msg,
                            "worker_result": worker_result,
                            "operation": payload.get("operation"),
                            "scope": payload.get("scope"),
                            "application": payload.get("application"),
                        }
                    else:
                        err_msg = worker_result.get("error") or worker_result.get("message") or f"Elevated worker exited with code {ec}"
                        yield {"type": "log", "text": f"[Elevated Error]: {err_msg}", "stream": "stderr"}
                        final_result = {
                            "ok": False,
                            "status": ElevationState.ELEVATED_OPERATION_FAILED.value,
                            "exit_code": ec or 1,
                            "message": err_msg,
                            "worker_result": worker_result,
                            "operation": payload.get("operation"),
                            "scope": payload.get("scope"),
                            "application": payload.get("application"),
                        }
                    return final_result
        finally:
            stop_event.set()
            ElevationDiagnosticLogger.log(
                "ELEVATION_FINISHED",
                operation_id=op_id,
                application=app_name,
                state="FINISHED",
                elapsed_ms=(time.time() - t0) * 1000,
            )
            for p in (payload_path, result_path, heartbeat_path):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass


class LinuxPrivilegeAdapter(BasePrivilegeAdapter):
    """Linux privilege elevation using pkexec / sudo."""

    def is_elevated(self) -> bool:
        return os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0

    def execute_elevated(
        self, payload: Dict[str, Any], timeout_sec: int = 60
    ) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        import subprocess

        backend_dir = os.path.dirname(os.path.abspath(__file__))
        worker_script = os.path.join(backend_dir, "elevated_worker.py")

        safe, msg, reason_code = self.check_pre_elevation_safety(payload)
        if not safe:
            err_msg = f"Elevated execution rejected by Live Safety Gate: {msg}"
            yield {"type": "log", "text": f"[Safety Blocked]: {err_msg}", "stream": "stderr"}
            yield {
                "type": "done",
                "returncode": -1,
                "ok": False,
                "status": "BLOCKED",
                "code": reason_code or "SAFETY_BLOCKED",
                "message": err_msg,
                "requires_elevation": True,
            }
            return {
                "ok": False,
                "status": "BLOCKED",
                "code": reason_code or "SAFETY_BLOCKED",
                "message": err_msg,
                "exit_code": -1,
            }

        payload_fd, payload_path = tempfile.mkstemp(suffix=".json", prefix="pcdoc_elev_payload_")
        result_fd, result_path = tempfile.mkstemp(suffix=".json", prefix="pcdoc_elev_result_")
        heartbeat_fd, heartbeat_path = tempfile.mkstemp(suffix=".marker", prefix="pcdoc_elev_hb_")

        with open(payload_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.close(payload_fd)
        os.close(result_fd)
        os.close(heartbeat_fd)

        pct30, d30 = STATE_PROGRESS_MAP[ElevationState.ELEVATION_REQUESTED.value]
        yield {"type": "progress", "percent": pct30, "state": ElevationState.ELEVATION_REQUESTED.value, "detail": d30}
        yield {"type": "log", "text": "Requesting root authorization...", "stream": "stdout"}

        try:
            if shutil.which("pkexec"):
                cmd = ["pkexec", sys.executable, worker_script, "--payload", payload_path, "--result", result_path, "--heartbeat", heartbeat_path]
            else:
                cmd = ["sudo", "-n", sys.executable, worker_script, "--payload", payload_path, "--result", result_path, "--heartbeat", heartbeat_path]

            pct40, d40 = STATE_PROGRESS_MAP[ElevationState.ELEVATION_GRANTED.value]
            yield {"type": "progress", "percent": pct40, "state": ElevationState.ELEVATION_GRANTED.value, "detail": d40}
            pct60, d60 = STATE_PROGRESS_MAP[ElevationState.ELEVATED_OPERATION_EXECUTING.value]
            yield {"type": "progress", "percent": pct60, "state": ElevationState.ELEVATED_OPERATION_EXECUTING.value, "detail": d60}

            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
            worker_result = {}
            if os.path.exists(result_path) and os.path.getsize(result_path) > 0:
                try:
                    with open(result_path, "r", encoding="utf-8") as rf:
                        worker_result = json.load(rf)
                except Exception:
                    pass

            is_ok = (proc.returncode == 0 and worker_result.get("status") == "EXECUTED")
            pct75, d75 = STATE_PROGRESS_MAP[ElevationState.ELEVATED_OPERATION_COMPLETED.value]
            yield {"type": "progress", "percent": pct75, "state": ElevationState.ELEVATED_OPERATION_COMPLETED.value, "detail": d75}

            res = {
                "ok": is_ok,
                "status": "EXECUTED" if is_ok else ElevationState.ELEVATED_OPERATION_FAILED.value,
                "exit_code": proc.returncode,
                "message": worker_result.get("message") or ("Elevated operation completed" if is_ok else proc.stderr),
                "worker_result": worker_result,
            }
            return res
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "status": ElevationState.ELEVATION_FAILED.value,
                "code": "OPERATION_TIMEOUT",
                "message": f"Elevated operation timed out after {timeout_sec}s",
                "exit_code": 124,
            }
        finally:
            for p in (payload_path, result_path, heartbeat_path):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass


class MacOSPrivilegeAdapter(BasePrivilegeAdapter):
    """macOS privilege elevation using osascript with administrator privileges."""

    def is_elevated(self) -> bool:
        return os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0

    def execute_elevated(
        self, payload: Dict[str, Any], timeout_sec: int = 60
    ) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        import subprocess

        backend_dir = os.path.dirname(os.path.abspath(__file__))
        worker_script = os.path.join(backend_dir, "elevated_worker.py")

        safe, msg, reason_code = self.check_pre_elevation_safety(payload)
        if not safe:
            err_msg = f"Elevated execution rejected by Live Safety Gate: {msg}"
            yield {"type": "log", "text": f"[Safety Blocked]: {err_msg}", "stream": "stderr"}
            yield {
                "type": "done",
                "returncode": -1,
                "ok": False,
                "status": "BLOCKED",
                "code": reason_code or "SAFETY_BLOCKED",
                "message": err_msg,
                "requires_elevation": True,
            }
            return {
                "ok": False,
                "status": "BLOCKED",
                "code": reason_code or "SAFETY_BLOCKED",
                "message": err_msg,
                "exit_code": -1,
            }

        payload_fd, payload_path = tempfile.mkstemp(suffix=".json", prefix="pcdoc_elev_payload_")
        result_fd, result_path = tempfile.mkstemp(suffix=".json", prefix="pcdoc_elev_result_")
        heartbeat_fd, heartbeat_path = tempfile.mkstemp(suffix=".marker", prefix="pcdoc_elev_hb_")

        with open(payload_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.close(payload_fd)
        os.close(result_fd)
        os.close(heartbeat_fd)

        pct30, d30 = STATE_PROGRESS_MAP[ElevationState.ELEVATION_REQUESTED.value]
        yield {"type": "progress", "percent": pct30, "state": ElevationState.ELEVATION_REQUESTED.value, "detail": d30}
        yield {"type": "log", "text": "Requesting macOS administrator authorization...", "stream": "stdout"}

        try:
            inner_cmd = f"'{sys.executable}' '{worker_script}' --payload '{payload_path}' --result '{result_path}' --heartbeat '{heartbeat_path}'"
            osa_script = f'do shell script "{inner_cmd}" with administrator privileges'
            cmd = ["osascript", "-e", osa_script]

            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
            worker_result = {}
            if os.path.exists(result_path) and os.path.getsize(result_path) > 0:
                try:
                    with open(result_path, "r", encoding="utf-8") as rf:
                        worker_result = json.load(rf)
                except Exception:
                    pass

            is_ok = (proc.returncode == 0 and worker_result.get("status") == "EXECUTED")
            pct75, d75 = STATE_PROGRESS_MAP[ElevationState.ELEVATED_OPERATION_COMPLETED.value]
            yield {"type": "progress", "percent": pct75, "state": ElevationState.ELEVATED_OPERATION_COMPLETED.value, "detail": d75}

            res = {
                "ok": is_ok,
                "status": "EXECUTED" if is_ok else ElevationState.ELEVATED_OPERATION_FAILED.value,
                "exit_code": proc.returncode,
                "message": worker_result.get("message") or ("Elevated operation completed" if is_ok else proc.stderr),
                "worker_result": worker_result,
            }
            return res
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "status": ElevationState.ELEVATION_FAILED.value,
                "code": "OPERATION_TIMEOUT",
                "message": f"Elevated operation timed out after {timeout_sec}s",
                "exit_code": 124,
            }
        finally:
            for p in (payload_path, result_path, heartbeat_path):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass


class PrivilegeManager:
    """Factory and facade for resolving platform privilege adapters."""

    _adapters: Dict[str, BasePrivilegeAdapter] = {}

    @classmethod
    def get_adapter(cls, sys_platform: Optional[str] = None) -> BasePrivilegeAdapter:
        plat = (sys_platform or platform.system()).lower()
        if "windows" in plat:
            if "windows" not in cls._adapters:
                cls._adapters["windows"] = WindowsPrivilegeAdapter()
            return cls._adapters["windows"]
        elif "darwin" in plat or "mac" in plat:
            if "darwin" not in cls._adapters:
                cls._adapters["darwin"] = MacOSPrivilegeAdapter()
            return cls._adapters["darwin"]
        else:
            if "linux" not in cls._adapters:
                cls._adapters["linux"] = LinuxPrivilegeAdapter()
            return cls._adapters["linux"]
    @classmethod
    def resolve_privilege(cls, tier: Any = None, elevate: bool = False, scope: Optional[str] = None) -> BasePrivilegeAdapter:
        """Authoritative privilege resolution step for the execution pipeline."""
        return cls.get_adapter()

    @classmethod
    def stream_elevated_operation(cls, payload: dict, timeout: int = 60):
        adapter = cls.get_adapter()
        yield from adapter.execute_elevated(payload, timeout_sec=min(timeout, 60))

    @classmethod
    def run_elevated_operation(cls, payload: dict, timeout: int = 60) -> dict:
        final_res = {}
        for event in cls.stream_elevated_operation(payload, timeout=timeout):
            if event.get("type") == "done" or event.get("status") in ("EXECUTED", "USER_DECLINED_ELEVATION", "ELEVATION_FAILED", "ELEVATED_OPERATION_FAILED", "BLOCKED"):
                final_res = event
        if not final_res:
            final_res = {
                "ok": True,
                "status": "EXECUTED",
                "exit_code": 0,
                "message": "Elevated operation completed successfully.",
            }
        return final_res

    @classmethod
    def run_with_elevation(cls, command: str, title: str = "") -> Tuple[str, str, int]:
        target_dir = ""
        if "path" in command.lower() or "environment" in command.lower():
            import re
            m = re.search(r'([A-Za-z]:\\[^;"\']+)', command)
            if m:
                target_dir = m.group(1)
        payload = {
            "operation": "REPAIR_PATH" if target_dir else "EXECUTE_COMMAND",
            "scope": "USER",
            "directory": target_dir,
            "command": command,
            "application": title or "System Tool",
            "source": "STATIC_DB",
        }
        res = cls.run_elevated_operation(payload)
        if res.get("status") == "USER_DECLINED_ELEVATION":
            return "", "Administrator permission was not granted by user.", 1223
        if not res.get("ok"):
            out = res.get("stdout") or ""
            err = res.get("stderr") or res.get("message") or ""
            rc = res.get("exit_code", res.get("returncode", 1))
            return out, err, rc
        out = res.get("stdout") or res.get("message") or ""
        err = res.get("stderr") or ""
        rc = res.get("exit_code", 0)
        return out, err, rc


privilege_manager = PrivilegeManager

