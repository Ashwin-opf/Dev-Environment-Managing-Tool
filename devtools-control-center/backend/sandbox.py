"""
Sandbox / Dry-Run Engine
========================
Simulates the predicted effects of a shell command before execution.
Produces a human-readable diff preview: files touched, env-vars set,
registry keys written (Windows), and services affected.

The sandbox never *runs* the command — it analyses the command string
statically and returns a structured prediction.  This is the "dry-run"
step that every pipeline action passes through before executor.run().
"""

from __future__ import annotations

import os
import platform
import re
import shutil
from typing import Any, Dict, List, Optional


# ─── helpers ──────────────────────────────────────────────────────────────────

def _classify_risk(effects: Dict[str, Any]) -> str:
    """Classify risk level based on predicted effects."""
    if effects.get("registry_writes") or effects.get("service_changes") or effects.get("requires_admin"):
        return "High"
    if effects.get("file_deletes") or effects.get("env_changes") or effects.get("network_access"):
        return "Medium"
    return "Low"


def _detect_env_changes(cmd: str) -> List[str]:
    """Extract environment variable assignments from a command string."""
    env_changes: List[str] = []
    # setx VAR value (Windows)
    for m in re.finditer(r'\bsetx\s+(\w+)\s+["\']?([^"\';\n]+)', cmd, re.IGNORECASE):
        env_changes.append(f"SET {m.group(1)}={m.group(2).strip()}")
    # export VAR=value (Unix)
    for m in re.finditer(r'\bexport\s+(\w+)=([^\s;]+)', cmd):
        env_changes.append(f"SET {m.group(1)}={m.group(2)}")
    # PATH extension patterns
    if "PATH" in cmd and ("=" in cmd or "append" in cmd.lower()):
        env_changes.append("MODIFY PATH")
    return env_changes


def _detect_file_deletes(cmd: str) -> List[str]:
    deletes: List[str] = []
    # rm -rf patterns
    for m in re.finditer(r'\brm\s+(?:-[a-z]+\s+)*([^\s;&|]+)', cmd, re.IGNORECASE):
        path = m.group(1)
        if not path.startswith("-"):
            deletes.append(path)
    # del /q /f (Windows)
    for m in re.finditer(r'\bdel\s+(?:/[qQfFsS]+\s+)*("[^"]+"|\S+)', cmd, re.IGNORECASE):
        deletes.append(m.group(1).strip('"'))
    return deletes[:10]


def _detect_file_writes(cmd: str) -> List[str]:
    writes: List[str] = []
    # Redirection operators
    for m in re.finditer(r'(?:>>?)\s*([^\s;&|]+)', cmd):
        writes.append(m.group(1))
    # tee targets
    for m in re.finditer(r'\btee\s+([^\s;&|]+)', cmd, re.IGNORECASE):
        writes.append(m.group(1))
    return writes[:10]


def _detect_registry_writes(cmd: str) -> List[str]:
    """Detect Windows registry modifications."""
    registry: List[str] = []
    if platform.system() != "Windows":
        return registry
    for m in re.finditer(r'\breg\s+(?:add|delete|import)\s+([^\s]+)', cmd, re.IGNORECASE):
        registry.append(m.group(1))
    for m in re.finditer(r'Set-ItemProperty\s+-Path\s+([^\s]+)', cmd, re.IGNORECASE):
        registry.append(m.group(1))
    return registry


def _detect_service_changes(cmd: str) -> List[str]:
    """Detect service start/stop/enable/disable actions."""
    services: List[str] = []
    # systemctl (Linux)
    for m in re.finditer(r'\bsystemctl\s+(?:start|stop|enable|disable|restart|mask|unmask)\s+(\S+)', cmd, re.IGNORECASE):
        services.append(m.group(1))
    # sc.exe (Windows)
    for m in re.finditer(r'\bsc\.exe?\s+(?:start|stop|create|delete)\s+(\S+)', cmd, re.IGNORECASE):
        services.append(m.group(1))
    return services


def _detect_network_access(cmd: str) -> bool:
    net_tokens = ["curl", "wget", "http://", "https://", "ftp://", "iwr", "invoke-webrequest",
                  "install.sh", "install.ps1"]
    lower = cmd.lower()
    return any(t in lower for t in net_tokens)


def _requires_admin(cmd: str) -> bool:
    return bool(re.search(r'\bsudo\b', cmd) or re.search(r'\brunas\b', cmd, re.IGNORECASE))


def _affected_packages(cmd: str) -> List[str]:
    """Extract package names from install/remove commands."""
    packages: List[str] = []
    pm_patterns = [
        r'\bapt(?:-get)?\s+(?:install|remove)\s+-?y?\s+(.+)',
        r'\bwinget\s+(?:install|uninstall)\s+(?:--id\s+)?(\S+)',
        r'\bdnf\s+(?:install|remove)\s+-?y?\s+(.+)',
        r'\bpacman\s+-S[a-z]*\s+(.+)',
        r'\bbrew\s+(?:install|uninstall)\s+(.+)',
        r'\bflatpak\s+(?:install|uninstall)\s+-?y?\s+(?:flathub\s+)?(.+)',
        r'\bsnap\s+(?:install|remove)\s+(.+)',
        r'\bpip[0-9]?\s+install\s+(.+)',
        r'\bnpm\s+install\s+-g?\s+(.+)',
        r'\bcargo\s+install\s+(.+)',
        r'\bchoco\s+install\s+(.+)',
        r'\bscoop\s+install\s+(.+)',
    ]
    for pattern in pm_patterns:
        m = re.search(pattern, cmd, re.IGNORECASE)
        if m:
            raw = m.group(1).strip().split()
            packages.extend(p for p in raw if not p.startswith("-"))
    return list(dict.fromkeys(packages))[:10]


# ─── main API ─────────────────────────────────────────────────────────────────

def dry_run(command: str) -> Dict[str, Any]:
    """
    Simulate the predicted effects of `command` without executing it.

    Returns:
        {
          "command": str,
          "risk": "Low" | "Medium" | "High",
          "requires_admin": bool,
          "network_access": bool,
          "predicted_effects": {
              "file_writes":       [str, ...],
              "file_deletes":      [str, ...],
              "env_changes":       [str, ...],
              "registry_writes":   [str, ...],   # Windows only
              "service_changes":   [str, ...],
              "packages_affected": [str, ...],
          },
          "warnings": [str, ...],
          "safe_to_proceed": bool,
        }
    """
    effects: Dict[str, Any] = {
        "file_writes":       _detect_file_writes(command),
        "file_deletes":      _detect_file_deletes(command),
        "env_changes":       _detect_env_changes(command),
        "registry_writes":   _detect_registry_writes(command),
        "service_changes":   _detect_service_changes(command),
        "packages_affected": _affected_packages(command),
    }
    requires_admin = _requires_admin(command)
    network_access = _detect_network_access(command)

    enriched = {**effects, "requires_admin": requires_admin, "network_access": network_access}
    risk = _classify_risk(enriched)

    # Build human-readable warnings
    warnings: List[str] = []
    if effects["file_deletes"]:
        warnings.append(f"Will delete files/directories: {', '.join(effects['file_deletes'][:5])}")
    if effects["registry_writes"]:
        warnings.append(f"Will modify registry keys: {', '.join(effects['registry_writes'][:3])}")
    if effects["service_changes"]:
        warnings.append(f"Will modify system services: {', '.join(effects['service_changes'][:3])}")
    if requires_admin:
        warnings.append("Requires elevated/administrator privileges.")
    if network_access:
        warnings.append("Will make network requests (downloads from internet).")

    # Absolute blocks — commands that match safety blacklist are never safe to proceed
    ABSOLUTE_BLOCKS = [
        r"rm\s+-rf\s+/\s*(?:$|[\s;&|])",
        r"rm\s+-rf\s+/\*",
        r"format\s+[Cc]:",
        r":\(\)\{.*:\|:",
        r"del.*windows[\\/]*system32",
        r"dd\s+if=.*of=/dev/",
    ]
    is_blocked = any(re.search(p, command, re.IGNORECASE) for p in ABSOLUTE_BLOCKS)

    return {
        "command": command,
        "risk": risk,
        "requires_admin": requires_admin,
        "network_access": network_access,
        "predicted_effects": effects,
        "warnings": warnings,
        "safe_to_proceed": not is_blocked,
        "blocked": is_blocked,
    }
