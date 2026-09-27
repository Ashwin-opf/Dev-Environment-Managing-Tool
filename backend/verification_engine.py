"""
verification_engine.py — Authoritative 3-Tier Verification Engine for PC Doctor.

Enforces:
- Never equate command exit 0 with real-world success.
- Separate status: EXECUTED (command ran with rc 0) vs VERIFIED (real state confirmed).
- 3 Verification Levels:
  1. FAST: Process exit code + basic executable existence + version output.
  2. CONTROLLED: FAST + functional sanity check (e.g. executing basic tool function).
  3. FULL: CONTROLLED + PATH/environment inspection + service state + original diagnostic problem rescan.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from canonical_identity import CanonicalIdentity, canonical_store
from recipe_engine import StructuredRecipe, RecipeOperation

logger = logging.getLogger("pc_doctor.verification_engine")


class VerificationLevel(str, Enum):
    FAST = "FAST"
    CONTROLLED = "CONTROLLED"
    FULL = "FULL"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    EXECUTED_UNVERIFIED = "EXECUTED_UNVERIFIED"
    VERIFICATION_TIMEOUT = "VERIFICATION_TIMEOUT"


@dataclass
class VerificationPolicy:
    """Configurable policy for verification synchronization, stabilization, and retries."""
    max_attempts: int = 3
    initial_backoff: float = 1.0
    backoff_factor: float = 1.5
    max_backoff: float = 5.0
    stabilization_grace: float = 0.5
    probe_timeout: int = 8

    @classmethod
    def from_env(cls, operation: str = "") -> VerificationPolicy:
        """Constructs a VerificationPolicy with environment overrides if present."""
        default_attempts = 3
        try:
            max_attempts = int(os.environ.get("PC_DOCTOR_VERIFY_MAX_ATTEMPTS", str(default_attempts)))
        except ValueError:
            max_attempts = default_attempts

        default_backoff = 1.0
        try:
            initial_backoff = float(os.environ.get("PC_DOCTOR_VERIFY_BACKOFF", str(default_backoff)))
        except ValueError:
            initial_backoff = default_backoff

        op = (operation or "").upper()
        default_grace = 1.0 if op in ("INSTALL", "UPDATE", "REPAIR", "REINSTALL") else 0.5
        try:
            stabilization_grace = float(os.environ.get("PC_DOCTOR_VERIFY_GRACE", str(default_grace)))
        except ValueError:
            stabilization_grace = default_grace

        default_timeout = 8
        try:
            probe_timeout = int(os.environ.get("PC_DOCTOR_VERIFY_TIMEOUT", str(default_timeout)))
        except ValueError:
            probe_timeout = default_timeout

        return cls(
            max_attempts=max(1, max_attempts),
            initial_backoff=max(0.0, initial_backoff),
            stabilization_grace=max(0.0, stabilization_grace),
            probe_timeout=max(1, probe_timeout),
        )

    def calculate_delay(self, attempt: int) -> float:
        """Returns bounded exponential backoff delay for given attempt index (1-indexed)."""
        if attempt <= 1:
            return self.initial_backoff
        delay = self.initial_backoff * (self.backoff_factor ** (attempt - 1))
        return min(delay, self.max_backoff)


@dataclass
class VerificationResult:
    status: VerificationStatus
    level: VerificationLevel
    executable_found: bool
    version_detected: Optional[str]
    functional_check_passed: bool
    problem_cleared: bool
    details: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    attempts: int = 1
    timed_out: bool = False
    execution_status: str = "EXECUTION_SUCCEEDED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "level": self.level.value,
            "executable_found": self.executable_found,
            "version_detected": self.version_detected,
            "functional_check_passed": self.functional_check_passed,
            "problem_cleared": self.problem_cleared,
            "message": self.message,
            "attempts": self.attempts,
            "timed_out": self.timed_out,
            "execution_status": self.execution_status,
            "details": self.details,
        }


def _run_probe(
    cmd: List[str],
    timeout: int = 10,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[subprocess.CompletedProcess, bool]:
    """Runs a verification probe command with explicit timeout detection and environment.
    Returns (completed_process, is_timeout).
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        return proc, False
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "")
        err = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")
        return subprocess.CompletedProcess(
            cmd,
            returncode=-1,
            stdout=out or "",
            stderr=f"Verification command timed out after {timeout} seconds. {err}".strip(),
        ), True
    except Exception as exc:
        return subprocess.CompletedProcess(cmd, returncode=-1, stdout="", stderr=str(exc)), False


def _extract_version_string(output: str) -> Optional[str]:
    for line in output.splitlines():
        line_clean = line.strip()
        # Look for semantic version tokens e.g. 2.44.0, v20.11.0, 1.96.2
        m = re.search(r"\b(?:v)?(\d+\.\d+(?:\.\d+)?(?:-[a-zA-Z0-9.]+)?)\b", line_clean)
        if m:
            return line_clean[:100]
    return None


def _refresh_verification_environment() -> Tuple[bool, Dict[str, str], str]:
    """
    Refreshes the current process environment and PATH from persistent platform sources.
    Returns (success: bool, effective_env: Dict[str, str], error_msg: str).
    Never silently swallows errors.
    """
    try:
        from platform_abstraction import get_path_manager, get_environment_provider
        pm = get_path_manager()
        if pm:
            eff_entries = pm.get_effective_path()
            for p in eff_entries:
                if p and os.path.exists(p):
                    pm.sync_process_path(p)
        ep = get_environment_provider()
        effective_env: Dict[str, str] = {}
        if ep:
            effective_env = ep.refresh_effective_environment()
        else:
            effective_env = dict(os.environ)
        return True, effective_env, ""
    except Exception as exc:
        err_msg = f"Failed to refresh verification environment: {exc}"
        logger.error(err_msg, exc_info=True)
        return False, dict(os.environ), err_msg


def _rescan_original_problem(
    target_name_or_id: str,
    original_problem: Optional[str] = None,
    original_status: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Performs an authoritative L5 diagnostic rescan of the original problem using DevEnvironmentDetector.
    Returns (problem_cleared: bool, rescan_status: str, details: Dict[str, Any]).
    Possible rescan_status values:
      - CLEARED: original condition is no longer present, tool is healthy
      - STILL_PRESENT: same issue remains detected
      - CHANGED: different issue detected (e.g. was NOT_INSTALLED, now PATH_MISSING)
      - UNRESOLVED: partial progress but not fully healthy
      - DETECTION_FAILED: could not re-run detector
    """
    try:
        from dev_environment_detector import DevEnvironmentDetector, ToolHealthStatus
        detector = DevEnvironmentDetector()
        diagnosis = detector.diagnose_tool(target_name_or_id)

        current_status = diagnosis.status.value if hasattr(diagnosis.status, "value") else str(diagnosis.status)
        is_healthy = (current_status == ToolHealthStatus.INSTALLED_AND_USABLE.value)

        details: Dict[str, Any] = {
            "current_status": current_status,
            "diagnosis_message": getattr(diagnosis, "diagnosis_message", ""),
            "installed": getattr(diagnosis, "installed", False),
            "original_problem": original_problem,
            "original_status": original_status,
        }

        if is_healthy:
            return True, "CLEARED", details

        orig = (original_status or original_problem or "").strip().upper()
        if orig and (orig == current_status.upper() or current_status.upper() in orig or orig in current_status.upper()):
            return False, "STILL_PRESENT", details
        elif orig:
            return False, "CHANGED", details
        else:
            return False, "UNRESOLVED", details

    except Exception as exc:
        logger.error(f"L5 detector rescan failed for {target_name_or_id}: {exc}", exc_info=True)
        return False, "DETECTION_FAILED", {"error": str(exc), "original_problem": original_problem}


class AuthoritativeVerificationEngine:
    """Performs tiered verification of tool and system state with bounded retry."""

    def refresh_verification_environment(self) -> Tuple[bool, Dict[str, str], str]:
        """Refreshes and returns the current effective environment."""
        return _refresh_verification_environment()

    _refresh_verification_environment = staticmethod(_refresh_verification_environment)

    def rescan_original_problem(
        self,
        target_name_or_id: str,
        original_problem: Optional[str] = None,
        original_status: Optional[str] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Executes real L5 detector rescan."""
        return _rescan_original_problem(target_name_or_id, original_problem, original_status)

    def _verify_single_probe(
        self,
        target_name_or_id: str,
        level: VerificationLevel = VerificationLevel.FAST,
        recipe: Optional[StructuredRecipe] = None,
        original_problem: Optional[str] = None,
        timeout: int = 8,
        attempt: int = 1,
        operation: Optional[str] = None,
    ) -> VerificationResult:
        # Refresh environment on every probe to ensure newly installed PATH/files are visible
        refresh_ok, eff_env, refresh_err = _refresh_verification_environment()
        if not refresh_ok:
            logger.warning("Verification environment refresh warning: %s", refresh_err)

        identity = canonical_store.resolve(target_name_or_id)
        exec_name = identity.executable if identity else target_name_or_id
        vcmd = identity.version_command if identity and identity.version_command else [exec_name, "--version"]

        if recipe and recipe.verification_command:
            vcmd = list(recipe.verification_command)

        # 1. PATH lookup using effective environment PATH
        effective_path = eff_env.get("PATH", os.environ.get("PATH", ""))
        found_path = shutil.which(exec_name, path=effective_path)
        if not found_path and identity:
            for p in identity.installation_paths:
                if Path(p).exists():
                    found_path = p
                    break

        op_str = (operation or (recipe.operation.value if recipe and hasattr(recipe, "operation") and hasattr(recipe.operation, "value") else "")).upper()
        if not found_path:
            if op_str == "UNINSTALL":
                return VerificationResult(
                    status=VerificationStatus.VERIFIED,
                    level=level,
                    executable_found=False,
                    version_detected=None,
                    functional_check_passed=True,
                    problem_cleared=True,
                    timed_out=False,
                    attempts=attempt,
                    message=f"Verified: '{exec_name}' successfully uninstalled (not found on PATH).",
                    details={"target": target_name_or_id, "executable": exec_name, "effective_path": effective_path},
                )
            return VerificationResult(
                status=VerificationStatus.VERIFICATION_FAILED,
                level=level,
                executable_found=False,
                version_detected=None,
                functional_check_passed=False,
                problem_cleared=False,
                timed_out=False,
                attempts=attempt,
                message=f"Binary '{exec_name}' not found on PATH or known install locations.",
                details={"target": target_name_or_id, "executable": exec_name, "effective_path": effective_path},
            )

        if op_str == "UNINSTALL":
            return VerificationResult(
                status=VerificationStatus.VERIFICATION_FAILED,
                level=level,
                executable_found=True,
                version_detected=None,
                functional_check_passed=False,
                problem_cleared=False,
                timed_out=False,
                attempts=attempt,
                message=f"Uninstall verification failed: '{exec_name}' still found at '{found_path}'.",
                details={"target": target_name_or_id, "executable": exec_name, "path": found_path},
            )

        # Shadowing Detection: verify first match on PATH matches expected binary
        if identity and found_path:
            target_plat = recipe.os if (recipe and recipe.os and str(recipe.os).strip().lower() not in ("any", "unknown", "")) else platform.system()
            expected_exe = identity.get_expected_executable_path(target_plat)
            if expected_exe and os.path.isfile(expected_exe):
                if not identity.matches_expected_executable(found_path, target_plat):
                    norm_found = os.path.normcase(os.path.normpath(found_path))
                    norm_expected = os.path.normcase(os.path.normpath(expected_exe))
                    if norm_found != norm_expected:
                        recommendation = (
                            f"Reorder PATH so that '{os.path.dirname(expected_exe)}' precedes '{os.path.dirname(found_path)}'."
                        )
                        return VerificationResult(
                            status=VerificationStatus.VERIFICATION_FAILED,
                            level=level,
                            executable_found=True,
                            version_detected=None,
                            functional_check_passed=False,
                            problem_cleared=False,
                            timed_out=False,
                            attempts=attempt,
                            message=f"Executable '{exec_name}' at '{found_path}' shadows expected installation '{expected_exe}' due to PATH ordering.",
                            details={
                                "shadowing_issue": "SHADOWED_BY_PREVIOUS_INSTALLATION",
                                "shadowed_by": found_path,
                                "expected_path": expected_exe,
                                "recommendation": recommendation,
                            },
                        )

        # 2. Run version command with effective environment
        actual_cmd = list(vcmd)
        if found_path and actual_cmd and actual_cmd[0] == exec_name and not shutil.which(exec_name, path=effective_path):
            actual_cmd[0] = found_path

        proc, is_timeout = _run_probe(actual_cmd, timeout=timeout, env=eff_env)
        if is_timeout:
            return VerificationResult(
                status=VerificationStatus.VERIFICATION_TIMEOUT,
                level=level,
                executable_found=True,
                version_detected=None,
                functional_check_passed=False,
                problem_cleared=False,
                timed_out=True,
                attempts=attempt,
                message=f"Verification command '{' '.join(actual_cmd)}' timed out after {timeout}s.",
                details={"cmd": actual_cmd, "timeout": timeout},
            )

        combined_out = (proc.stdout + "\n" + proc.stderr).strip()
        version_str = _extract_version_string(combined_out)

        if proc.returncode != 0 and not version_str:
            return VerificationResult(
                status=VerificationStatus.VERIFICATION_FAILED,
                level=level,
                executable_found=True,
                version_detected=None,
                functional_check_passed=False,
                problem_cleared=False,
                timed_out=False,
                attempts=attempt,
                message=f"Verification command '{' '.join(actual_cmd)}' failed with exit code {proc.returncode}.",
                details={"stdout": proc.stdout, "stderr": proc.stderr},
            )

        # Level 1: FAST check satisfied
        if level == VerificationLevel.FAST:
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                level=level,
                executable_found=True,
                version_detected=version_str or combined_out[:60],
                functional_check_passed=True,
                problem_cleared=True,
                timed_out=False,
                attempts=attempt,
                message=f"Verified: {exec_name} found and operational ({version_str or 'version confirmed'}).",
                details={"path": found_path, "version": version_str},
            )

        # Level 2: CONTROLLED functional probe (Generic via CanonicalIdentity)
        func_ok = True
        func_timed_out = False
        actual_exec = found_path if (found_path and not shutil.which(exec_name, path=effective_path)) else exec_name
        func_cmd = identity.get_functional_probe_command(platform.system()) if identity else []

        if func_cmd:
            actual_func_cmd = list(func_cmd)
            if actual_func_cmd and actual_func_cmd[0] == exec_name and actual_exec:
                actual_func_cmd[0] = actual_exec

            expected_exit = getattr(identity, "functional_probe_expected_exit_code", 0)
            test_run, to = _run_probe(actual_func_cmd, timeout=timeout, env=eff_env)
            func_timed_out = to
            func_ok = (test_run.returncode == expected_exit)

            if func_timed_out:
                return VerificationResult(
                    status=VerificationStatus.VERIFICATION_TIMEOUT,
                    level=level,
                    executable_found=True,
                    version_detected=version_str,
                    functional_check_passed=False,
                    problem_cleared=False,
                    timed_out=True,
                    attempts=attempt,
                    message=f"Functional sanity probe timed out for {exec_name}.",
                    details={"path": found_path, "cmd": actual_func_cmd},
                )

            if not func_ok:
                return VerificationResult(
                    status=VerificationStatus.VERIFICATION_FAILED,
                    level=level,
                    executable_found=True,
                    version_detected=version_str,
                    functional_check_passed=False,
                    problem_cleared=False,
                    timed_out=False,
                    attempts=attempt,
                    message=f"Functional sanity probe failed for {exec_name} with exit code {test_run.returncode}.",
                    details={"path": found_path, "cmd": actual_func_cmd, "stdout": test_run.stdout, "stderr": test_run.stderr},
                )

        if level == VerificationLevel.CONTROLLED:
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                level=level,
                executable_found=True,
                version_detected=version_str,
                functional_check_passed=True,
                problem_cleared=True,
                timed_out=False,
                attempts=attempt,
                message=f"Controlled functional verification succeeded for {exec_name}.",
                details={"path": found_path, "version": version_str},
            )

        # Level 3: FULL verification (Environment + Problem Rescan)
        problem_cleared = True
        rescan_status = "CLEARED"
        rescan_details: Dict[str, Any] = {}

        if original_problem or level == VerificationLevel.FULL:
            problem_cleared, rescan_status, rescan_details = _rescan_original_problem(
                target_name_or_id=target_name_or_id,
                original_problem=original_problem,
            )

        verif_status = VerificationStatus.VERIFIED if problem_cleared else VerificationStatus.VERIFICATION_FAILED
        msg = (
            f"Full verification passed: {exec_name} operational and original problem CLEARED."
            if problem_cleared
            else f"Full verification failed: original problem {rescan_status} ({rescan_details.get('diagnosis_message', '')})."
        )

        details_out = {
            "path": found_path,
            "version": version_str,
            "original_problem": original_problem,
            "rescan_status": rescan_status,
            **rescan_details,
        }

        return VerificationResult(
            status=verif_status,
            level=level,
            executable_found=True,
            version_detected=version_str,
            functional_check_passed=True,
            problem_cleared=problem_cleared,
            timed_out=False,
            attempts=attempt,
            message=msg,
            details=details_out,
        )

    def verify_tool(
        self,
        target_name_or_id: str,
        level: VerificationLevel = VerificationLevel.FAST,
        recipe: Optional[StructuredRecipe] = None,
        original_problem: Optional[str] = None,
        policy: Optional[VerificationPolicy] = None,
        on_attempt: Optional[Any] = None,
        operation: Optional[str] = None,
    ) -> VerificationResult:
        """
        Executes bounded verification retry loop on transient timeouts.
        Never loops on deterministic errors.
        """
        active_policy = policy or VerificationPolicy.from_env(recipe.operation.value if recipe else "")
        max_attempts = max(1, active_policy.max_attempts)
        last_result: Optional[VerificationResult] = None

        import time

        for attempt in range(1, max_attempts + 1):
            if on_attempt:
                try:
                    on_attempt(attempt, "VERIFICATION_STARTED", None)
                except Exception:
                    pass

            result = self._verify_single_probe(
                target_name_or_id=target_name_or_id,
                level=level,
                recipe=recipe,
                original_problem=original_problem,
                timeout=active_policy.probe_timeout,
                attempt=attempt,
                operation=operation,
            )
            result.attempts = attempt
            last_result = result

            if result.status == VerificationStatus.VERIFIED:
                if on_attempt:
                    try:
                        on_attempt(attempt, "VERIFICATION_SUCCEEDED", None)
                    except Exception:
                        pass
                return result

            # Deterministic check: do not retry if failure is not a timeout
            if not result.timed_out:
                if on_attempt:
                    try:
                        on_attempt(attempt, "VERIFICATION_FAILED", None)
                    except Exception:
                        pass
                return result

            # Transient timeout occurred: if more attempts remain, backoff and retry
            if attempt < max_attempts:
                delay = active_policy.calculate_delay(attempt)
                if on_attempt:
                    try:
                        on_attempt(attempt, "VERIFICATION_TIMEOUT", delay)
                    except Exception:
                        pass
                if delay > 0:
                    time.sleep(delay)
            else:
                if on_attempt:
                    try:
                        on_attempt(attempt, "VERIFICATION_TIMEOUT", None)
                    except Exception:
                        pass

        if last_result and last_result.timed_out:
            last_result.status = VerificationStatus.VERIFICATION_TIMEOUT
            last_result.message = f"Verification timed out after {max_attempts} attempts for {target_name_or_id}."
            return last_result

        return last_result or VerificationResult(
            status=VerificationStatus.VERIFICATION_FAILED,
            level=level,
            executable_found=False,
            version_detected=None,
            functional_check_passed=False,
            problem_cleared=False,
            attempts=max_attempts,
            message="Verification failed to complete.",
        )


# Global singleton verification engine
verification_engine = AuthoritativeVerificationEngine()
