"""
result_classifier.py — Standardized Execution Result Classifier for PC Doctor.

Parses command outputs from package managers (winget, apt, brew, pip, npm, etc.)
and system execution engines. Classifies results into 8 distinct statuses:
  - SUCCESS
  - UPDATE_NOT_AVAILABLE
  - UPDATE_UNSUPPORTED_BY_PACKAGE_MANAGER
  - PACKAGE_NOT_FOUND
  - PERMISSION_DENIED
  - NETWORK_ERROR
  - VERIFICATION_FAILED
  - COMMAND_EXECUTION_FAILED

Provides publisher metadata, official links, and verified alternative commands
for publisher-managed applications.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).parent / "knowledge_static.db"

# Well-known publisher-managed packages where package manager updates are restricted
KNOWN_PUBLISHER_MANAGED: dict[str, dict[str, Any]] = {
    "anaconda.anaconda3": {
        "tool_name": "Anaconda3",
        "update_supported": False,
        "update_method": "PUBLISHER_RECIPE",
        "official_url": "https://www.anaconda.com/download",
        "publisher_update_command": "conda update --all -y",
        "publisher_update_instructions": "To update Anaconda, run 'conda update --all' in the Anaconda Prompt or download the installer from the official Anaconda website.",
    },
    "anaconda3": {
        "tool_name": "Anaconda3",
        "update_supported": False,
        "update_method": "PUBLISHER_RECIPE",
        "official_url": "https://www.anaconda.com/download",
        "publisher_update_command": "conda update --all -y",
        "publisher_update_instructions": "To update Anaconda, run 'conda update --all' in the Anaconda Prompt or download the installer from the official Anaconda website.",
    },
    "miniconda3": {
        "tool_name": "Miniconda3",
        "update_supported": False,
        "update_method": "PUBLISHER_RECIPE",
        "official_url": "https://docs.anaconda.com/miniconda/",
        "publisher_update_command": "conda update --all -y",
        "publisher_update_instructions": "To update Miniconda, run 'conda update --all' in Anaconda Prompt.",
    },
}

# In-memory runtime cache for dynamically detected publisher-managed packages
_DYNAMIC_PUBLISHER_MANAGED_CACHE: dict[str, dict[str, Any]] = {}


def register_publisher_managed_package(package_id: str, info: dict[str, Any]) -> None:
    """Record a package that was dynamically discovered to be publisher-managed."""
    clean_id = (package_id or "").strip().lower()
    if clean_id:
        _DYNAMIC_PUBLISHER_MANAGED_CACHE[clean_id] = info


def get_publisher_managed_info(package_id: str, app_name: str = "") -> Optional[dict[str, Any]]:
    """Look up known capability metadata for a package."""
    clean_id = (package_id or "").strip().lower()
    clean_name = (app_name or "").strip().lower()

    if not clean_id and not clean_name:
        return None

    if clean_id in KNOWN_PUBLISHER_MANAGED:
        return KNOWN_PUBLISHER_MANAGED[clean_id]
    if clean_name in KNOWN_PUBLISHER_MANAGED:
        return KNOWN_PUBLISHER_MANAGED[clean_name]
    if clean_id in _DYNAMIC_PUBLISHER_MANAGED_CACHE:
        return _DYNAMIC_PUBLISHER_MANAGED_CACHE[clean_id]
    if clean_name in _DYNAMIC_PUBLISHER_MANAGED_CACHE:
        return _DYNAMIC_PUBLISHER_MANAGED_CACHE[clean_name]

    # Query static DB for publisher recipe
    if DB_PATH.exists():
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                where_clauses = []
                params = []
                if clean_id:
                    where_clauses.append("LOWER(package_id) = ?")
                    params.append(clean_id)
                if clean_name:
                    where_clauses.append("LOWER(app_id) = ?")
                    params.append(clean_name)
                    where_clauses.append("LOWER(issue) LIKE ?")
                    params.append(f"%{clean_name}%")
                
                if not where_clauses:
                    return None

                query = f"""
                    SELECT issue, package_id, official_url, update_supported,
                           update_method, publisher_update_command, publisher_update_instructions
                    FROM static_recipes
                    WHERE ({' OR '.join(where_clauses)})
                      AND (update_supported = 0 OR update_method IN ('PUBLISHER', 'PUBLISHER_RECIPE'))
                    LIMIT 1
                """
                row = conn.execute(query, tuple(params)).fetchone()
                if row:
                    return {
                        "tool_name": row["issue"],
                        "update_supported": bool(row["update_supported"]),
                        "update_method": row["update_method"] or "PUBLISHER",
                        "official_url": row["official_url"] or "",
                        "publisher_update_command": row["publisher_update_command"] or "",
                        "publisher_update_instructions": row["publisher_update_instructions"] or "",
                    }
        except Exception:
            pass

    return None


def classify_execution_result(
    command: str,
    returncode: int,
    stdout: str = "",
    stderr: str = "",
    operation: str = "UPDATE",
    app_name: str = "",
    package_id: str = "",
) -> dict[str, Any]:
    """
    Evaluates real output from package managers and assigns an accurate status code,
    user-facing explanation, and next-step actions.
    """
    combined = f"{stdout}\n{stderr}".strip()
    combined_lower = combined.lower()
    cmd_lower = (command or "").lower()

    # 1. Check for publisher-managed / unsupported update message (WinGet & others)
    # WinGet message: "The package cannot be upgraded using WinGet. Please use the method provided by the publisher for upgrading this package."
    is_publisher_msg = (
        "cannot be upgraded using winget" in combined_lower
        or "method provided by the publisher" in combined_lower
        or "use the method provided by the publisher" in combined_lower
        or "publisher-managed" in combined_lower
        or "publisher for upgrading this package" in combined_lower
        or ("package cannot be upgraded" in combined_lower and "publisher" in combined_lower)
    )

    # Extract package_id from command if not explicitly supplied
    if not package_id:
        match = re.search(r'--id\s+["\']?([^"\'\s]+)["\']?', command)
        if match:
            package_id = match.group(1)

    # Check if this package is already known to be publisher-managed
    pub_info = get_publisher_managed_info(package_id, app_name)

    if is_publisher_msg or (pub_info and pub_info.get("update_supported") is False and "upgrade" in cmd_lower and returncode != 0):
        # Dynamically remember that this package cannot be upgraded through WinGet
        if package_id:
            register_publisher_managed_package(package_id, {
                "update_supported": False,
                "update_method": pub_info.get("update_method") if pub_info else "PUBLISHER",
                "official_url": pub_info.get("official_url") if pub_info else "",
                "publisher_update_command": pub_info.get("publisher_update_command") if pub_info else "",
                "publisher_update_instructions": pub_info.get("publisher_update_instructions") if pub_info else "",
            })

        display_name = app_name or (pub_info.get("tool_name") if pub_info else None) or package_id or "This application"
        official_url = (pub_info and pub_info.get("official_url")) or ""
        pub_cmd = (pub_info and pub_info.get("publisher_update_command")) or ""
        pub_inst = (pub_info and pub_info.get("publisher_update_instructions")) or ""

        if not pub_inst:
            pub_inst = (
                f"{display_name} is installed, but this package cannot be upgraded using WinGet. "
                f"Please use the method provided by the publisher for upgrading this package."
            )

        return {
            "classification": "UPDATE_UNSUPPORTED_BY_PACKAGE_MANAGER",
            "code": "UPDATE_UNSUPPORTED_BY_PACKAGE_MANAGER",
            "is_success": False,
            "returncode": returncode,
            "is_publisher_managed": True,
            "app_name": display_name,
            "package_id": package_id,
            "title": "Update Unavailable through Package Manager",
            "explanation": f"{display_name} cannot be upgraded using WinGet. Upgrades for this package are managed directly by the publisher.",
            "instructions": pub_inst,
            "official_url": official_url,
            "publisher_update_command": pub_cmd,
            "publisher_update_instructions": pub_inst,
            "action_recommended": "PUBLISHER_UPDATE" if (pub_cmd or official_url) else "OPEN_OFFICIAL_SITE",
            "retry_supported": False,
        }

    # 2. Check for Permission Denied / Elevation Required
    if any(p in combined_lower for p in (
        "access is denied",
        "administrator privileges required",
        "requires elevation",
        "run as administrator",
        "elevation required",
        "0x80070005",
        "permission denied",
        "must be root",
    )):
        return {
            "classification": "PERMISSION_DENIED",
            "code": "PERMISSION_DENIED",
            "is_success": False,
            "returncode": returncode,
            "is_publisher_managed": False,
            "title": "Administrator Privileges Required",
            "explanation": "This operation requires elevated administrative privileges. Please launch PC Doctor as Administrator.",
            "action_recommended": "RUN_AS_ADMIN",
            "retry_supported": True,
        }

    # 3. Check for Network / Connectivity Errors
    if any(p in combined_lower for p in (
        "0x80072ee7",
        "0x80072efd",
        "0x80072efe",
        "0x80190194",
        "failed to connect",
        "connection failed",
        "could not resolve host",
        "network error",
        "temporary failure resolving",
        "connection timed out",
    )):
        return {
            "classification": "NETWORK_ERROR",
            "code": "NETWORK_ERROR",
            "is_success": False,
            "returncode": returncode,
            "is_publisher_managed": False,
            "title": "Network Connection Issue",
            "explanation": "Failed to connect to the package repository. Please verify your internet connection and DNS settings.",
            "action_recommended": "RETRY_NETWORK",
            "retry_supported": True,
        }

    # 4. Check for Package Not Found
    if any(p in combined_lower for p in (
        "no installed package found",
        "no package found matching",
        "no package found",
        "package not found",
        "unable to locate package",
        "0x80070002",
    )):
        return {
            "classification": "PACKAGE_NOT_FOUND",
            "code": "PACKAGE_NOT_FOUND",
            "is_success": False,
            "returncode": returncode,
            "is_publisher_managed": False,
            "title": "Package Not Found",
            "explanation": f"The package was not found in the local or remote package catalog.",
            "action_recommended": "CHECK_CATALOG",
            "retry_supported": False,
        }

    # 5. Check for Update Not Available (Already up to date)
    if any(p in combined_lower for p in (
        "no applicable update found",
        "no available upgrade found",
        "no available update found",
        "already installed",
        "is already up-to-date",
        "is up to date",
        "0 upgraded, 0 newly installed",
    )):
        return {
            "classification": "UPDATE_NOT_AVAILABLE",
            "code": "UPDATE_NOT_AVAILABLE",
            "is_success": True,  # Already at target state
            "returncode": returncode,
            "is_publisher_managed": False,
            "title": "Already Up to Date",
            "explanation": "No applicable updates found. The package is already running the latest version available in this source.",
            "action_recommended": "NONE",
            "retry_supported": False,
        }

    # 6. Check for Verification / Checksum Failures
    if any(p in combined_lower for p in (
        "hash mismatch",
        "checksum mismatch",
        "signature verification failed",
        "integrity verification failed",
        "installer hash does not match",
    )):
        return {
            "classification": "VERIFICATION_FAILED",
            "code": "VERIFICATION_FAILED",
            "is_success": False,
            "returncode": returncode,
            "is_publisher_managed": False,
            "title": "Installer Hash Verification Failed",
            "explanation": "The downloaded installer package failed integrity checksum verification. Download was aborted for security.",
            "action_recommended": "PURGE_CACHE",
            "retry_supported": True,
        }

    # 7. Check for clean 0 return code
    if returncode == 0:
        return {
            "classification": "SUCCESS",
            "code": "SUCCESS",
            "is_success": True,
            "returncode": 0,
            "is_publisher_managed": False,
            "title": "Operation Succeeded",
            "explanation": "The command completed successfully.",
            "action_recommended": "NONE",
            "retry_supported": False,
        }

    # 8. General execution failure
    return {
        "classification": "COMMAND_EXECUTION_FAILED",
        "code": "COMMAND_EXECUTION_FAILED",
        "is_success": False,
        "returncode": returncode,
        "is_publisher_managed": False,
        "title": "Execution Failed",
        "explanation": f"The operation returned non-zero exit code ({returncode}). Check output for details.",
        "action_recommended": "NORMAL_FAILURE",
        "retry_supported": True,
    }
