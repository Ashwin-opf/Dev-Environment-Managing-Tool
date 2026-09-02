"""
Risk Assessment Engine
======================
Dynamically computes risk tiers for any action based on:
  - Command blast radius (sandbox dry-run analysis)
  - Current system load (CPU/RAM — warns before heavy installs)
  - Confidence scoring

Shared risk engine used across DevTools installation and Control Center approval workflows.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


# Thresholds above which a new heavy operation is risky
CPU_WARN_PCT    = 80.0
RAM_WARN_PCT    = 85.0

# Risk tier labels
RISK_LOW    = "Low"
RISK_MEDIUM = "Medium"
RISK_HIGH   = "High"


def _get_system_load() -> Dict[str, float]:
    if not _HAS_PSUTIL:
        return {"cpu": 0.0, "ram": 0.0, "gpu": 0.0}
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory().percent
        return {"cpu": cpu, "ram": ram, "gpu": 0.0}
    except Exception:
        return {"cpu": 0.0, "ram": 0.0, "gpu": 0.0}


def assess(action: Dict[str, Any], kb_history: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Compute a dynamic risk tier for `action`.

    Parameters
    ----------
    action : dict
        Must contain at least: ``command`` (str), optionally ``target`` (str),
        ``dry_run_result`` (dict from sandbox.dry_run).
    kb_history : dict, optional
        Pre-fetched metadata / history if available.

    Returns
    -------
    dict with keys: tier, score, reasons, system_load, kb_confidence.
    """
    command     = action.get("command", "")
    target      = action.get("target", command[:40])
    dry_result  = action.get("dry_run_result") or {}

    reasons: list[str] = []
    score = 0  # 0=Low, 1=Medium, 2=High

    # 1. Dry-run blast radius
    sandbox_risk = dry_result.get("risk", RISK_LOW)
    if sandbox_risk == RISK_HIGH:
        score += 2
        reasons.append("Command has high blast radius (registry/service changes detected).")
    elif sandbox_risk == RISK_MEDIUM:
        score += 1
        reasons.append("Command has medium blast radius (file deletes / env changes).")

    if dry_result.get("blocked"):
        score = 999  # always block
        reasons.append("Command matches block list — execution refused.")

    if dry_result.get("requires_admin"):
        score += 1
        reasons.append("Command requires elevated / administrator privileges.")

    # 2. Confidence factor
    confidence = float(kb_history.get("confidence", 0.7)) if kb_history else 0.75
    if confidence < 0.4:
        score += 1
        reasons.append(f"Low confidence ({confidence:.0%}) — unverified package recipe.")

    # 3. System load warning
    load = _get_system_load()
    load_warnings: list[str] = []
    if load["cpu"] >= CPU_WARN_PCT:
        load_warnings.append(f"CPU at {load['cpu']:.0f}%")
    if load["ram"] >= RAM_WARN_PCT:
        load_warnings.append(f"RAM at {load['ram']:.0f}%")
    if load_warnings:
        score += 1
        reasons.append("High system load: " + ", ".join(load_warnings) + ". Consider waiting.")

    # Map score → tier
    if score >= 2:
        tier = RISK_HIGH
    elif score == 1:
        tier = RISK_MEDIUM
    else:
        tier = RISK_LOW

    return {
        "tier": tier,
        "score": score,
        "reasons": reasons,
        "system_load": load,
        "kb_confidence": round(confidence, 3),
        "blocked": dry_result.get("blocked", False),
    }
