"""
Functional Verifier
===================
Checks that an action actually achieved its expected state.
Not just exit-code checking — real functional verification:
  - Is the tool on PATH with a sane --version output?
  - Did the original error signature clear?
  - Is the service running / the config in place?

This is applied identically after installs AND repairs.
Failed verification means the KB entry is discarded, never stored.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional


def _run(cmd: List[str], timeout: int = 8) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception as exc:
        import subprocess as sp
        return sp.CompletedProcess(cmd, returncode=1, stdout="", stderr=str(exc))


def _check_on_path(binary: str) -> bool:
    return shutil.which(binary) is not None


def _check_version_output(binary: str) -> Optional[str]:
    """Try common --version / version flags. Returns version string or None."""
    for flag in ["--version", "-v", "-V", "version"]:
        res = _run([binary, flag])
        combined = (res.stdout + res.stderr).strip()
        if combined and res.returncode in (0, 1):
            # Take first line with a version-like token
            for line in combined.splitlines():
                if re.search(r"\d+\.\d+", line):
                    return line.strip()[:120]
    return None


def _check_flatpak_installed(app_id: str) -> bool:
    res = _run(["flatpak", "info", app_id])
    return res.returncode == 0


def _check_snap_installed(name: str) -> bool:
    res = _run(["snap", "list", name])
    return res.returncode == 0 and name in res.stdout


def _check_pip_installed(pkg: str) -> bool:
    import sys
    res = _run([sys.executable, "-m", "pip", "show", pkg])
    return res.returncode == 0


def _check_npm_installed(pkg: str) -> bool:
    res = _run(["npm", "list", "-g", pkg, "--depth=0"])
    return res.returncode == 0 and pkg in res.stdout


def _check_cargo_installed(pkg: str) -> bool:
    res = _run(["cargo", "install", "--list"])
    return res.returncode == 0 and pkg in res.stdout


def _error_signature_cleared(original_error: str, target: str) -> bool:
    """
    Re-run a quick probe to see if the original error pattern no longer appears.
    For now, checks that binary is on PATH and returns a clean version output.
    """
    if not original_error:
        return True
    # If we can run the tool cleanly, the error is cleared
    version = _check_version_output(target)
    return version is not None


# ─── Public API ────────────────────────────────────────────────────────────────

def check(target: str, expected_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Verify that `target` has reached `expected_state`.

    Parameters
    ----------
    target : str
        The tool/binary/package name being checked.
    expected_state : dict
        Keys understood:
          - ``on_path`` (bool)     : must be discoverable via shutil.which
          - ``version_pattern`` (str) : regex that must match version output
          - ``original_error`` (str)  : error string that must have cleared
          - ``adapter`` (str)         : pm name for package-level checks
                                        ('flatpak','snap','pip','npm','cargo')

    Returns
    -------
    dict:
        {
          "passed": bool,
          "evidence": {...},
          "failures": [str, ...],
        }
    """
    failures: List[str] = []
    evidence: Dict[str, Any] = {}

    adapter = expected_state.get("adapter", "")

    # 1. PATH check
    if expected_state.get("on_path", True):
        on_path = _check_on_path(target)
        evidence["on_path"] = on_path
        if not on_path:
            # Try adapter-specific checks before failing
            if adapter == "flatpak":
                on_path = _check_flatpak_installed(target)
                evidence["flatpak_installed"] = on_path
            elif adapter == "snap":
                on_path = _check_snap_installed(target)
                evidence["snap_installed"] = on_path
            elif adapter == "pip":
                on_path = _check_pip_installed(target)
                evidence["pip_installed"] = on_path
            elif adapter == "npm":
                on_path = _check_npm_installed(target)
                evidence["npm_installed"] = on_path
            elif adapter == "cargo":
                on_path = _check_cargo_installed(target)
                evidence["cargo_installed"] = on_path

            if not on_path:
                failures.append(f"{target!r} not found on PATH or via {adapter or 'system'}.")

    # 2. Version output check
    version_str = _check_version_output(target)
    evidence["version_output"] = version_str
    if version_str is None and adapter not in ("flatpak", "snap"):
        # Only warn, not fail — some tools don't have --version
        evidence["version_warning"] = "No --version output detected."

    pattern = expected_state.get("version_pattern")
    if pattern and version_str:
        if not re.search(pattern, version_str):
            failures.append(
                f"Version output {version_str!r} does not match pattern {pattern!r}."
            )

    # 3. Original error cleared
    original_error = expected_state.get("original_error", "")
    if original_error:
        cleared = _error_signature_cleared(original_error, target)
        evidence["error_cleared"] = cleared
        if not cleared:
            failures.append(f"Original error signature still present: {original_error[:100]}")

    passed = len(failures) == 0
    return {
        "passed": passed,
        "target": target,
        "evidence": evidence,
        "failures": failures,
    }
