"""
Risk Assessment Engine
======================
Dynamically computes risk tiers for any action based on:
  - Command blast radius (sandbox dry-run analysis)
  - Current system load (CPU/GPU/RAM — warns before heavy installs)
  - Historical knowledge-base confidence for this recipe
  - Whether the recipe is a first-time or well-reused entry

This is the SINGLE shared risk engine used by Search, Pipeline, Repair,
Driver, and AI Terminal. Not five separate calculations.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


# Thresholds above which a new heavy operation is risky
CPU_WARN_PCT    = 80.0
GPU_WARN_PCT    = 80.0
RAM_WARN_PCT    = 85.0

# Risk tier labels
RISK_LOW    = "Low"
RISK_MEDIUM = "Medium"
RISK_HIGH   = "High"


# ─── KB confidence lookup ─────────────────────────────────────────────────────

def _kb_confidence(target: str, db_path: Optional[str] = None) -> float:
    """
    Return a confidence score [0.0 – 1.0] for `target` from the knowledge base.
    Higher = more verified runs, lower = first-time or demoted.
    """
    if db_path is None:
        db_path = str(Path(__file__).parent / "knowledge.db")
    try:
        con = sqlite3.connect(db_path, timeout=3)
        cur = con.cursor()
        # Try the SHCE error_intelligence table first
        try:
            cur.execute(
                "SELECT confidence, reuse_count FROM error_intelligence "
                "WHERE target = ? ORDER BY reuse_count DESC LIMIT 1",
                (target,),
            )
            row = cur.fetchone()
            if row:
                confidence, reuse_count = row
                # Decay: each failed reuse lowers effective confidence
                return min(1.0, float(confidence or 0.5) * (1 + 0.05 * int(reuse_count or 0)))
        except sqlite3.OperationalError:
            pass
        # Fallback: repair_recipes table
        try:
            cur.execute(
                "SELECT COUNT(*) FROM repair_recipes WHERE issue LIKE ?",
                (f"%{target}%",),
            )
            count = cur.fetchone()[0] or 0
            return 0.5 + min(0.4, count * 0.05)
        except sqlite3.OperationalError:
            pass
        con.close()
    except Exception:
        pass
    return 0.3  # unknown → low confidence = higher risk


# ─── System load snapshot ─────────────────────────────────────────────────────

def _get_system_load() -> Dict[str, float]:
    if not _HAS_PSUTIL:
        return {"cpu": 0.0, "ram": 0.0, "gpu": 0.0}
    cpu = psutil.cpu_percent(interval=0.3)
    ram = psutil.virtual_memory().percent
    gpu = 0.0
    try:
        from platform_hw import get_gpu_usage_info as _gpu_info
        gpu_data = _gpu_info()
        if isinstance(gpu_data, list) and gpu_data:
            gpu = float(gpu_data[0].get("utilization", 0) or 0)
        elif isinstance(gpu_data, dict):
            gpu = float(gpu_data.get("utilization", 0) or 0)
    except Exception:
        pass
    return {"cpu": cpu, "ram": ram, "gpu": gpu}


# ─── Risk tier logic ──────────────────────────────────────────────────────────

def assess(action: Dict[str, Any], kb_history: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Compute a risk tier for `action`.

    Parameters
    ----------
    action : dict
        Must contain at least: ``command`` (str), optionally ``target`` (str),
        ``dry_run_result`` (dict from sandbox.dry_run).
    kb_history : dict, optional
        Pre-fetched KB record. If None, looked up from DB.

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
        reasons.append("Command matches absolute block list — execution refused.")

    if dry_result.get("requires_admin"):
        score += 1
        reasons.append("Command requires elevated / administrator privileges.")

    # 2. KB confidence
    confidence = (
        float(kb_history.get("confidence", 0.3)) if kb_history
        else _kb_confidence(target)
    )
    if confidence < 0.4:
        score += 1
        reasons.append(f"Low KB confidence ({confidence:.0%}) — first-time or unverified recipe.")
    elif confidence >= 0.85:
        score = max(0, score - 1)
        reasons.append(f"High KB confidence ({confidence:.0%}) from verified history.")

    # 3. System load warning
    load = _get_system_load()
    load_warnings: list[str] = []
    if load["cpu"] >= CPU_WARN_PCT:
        load_warnings.append(f"CPU at {load['cpu']:.0f}%")
    if load["ram"] >= RAM_WARN_PCT:
        load_warnings.append(f"RAM at {load['ram']:.0f}%")
    if load["gpu"] >= GPU_WARN_PCT:
        load_warnings.append(f"GPU at {load['gpu']:.0f}%")
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
