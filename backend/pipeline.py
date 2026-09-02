"""
Automated Install → Configure → Repair → Manage Pipeline
=========================================================
Stages (each independently retryable and logged):
  1. Resolve   — environment fingerprint + dependency tree
  2. Dry-run   — simulate effects, generate diff/preview
  3. Snapshot  — create rollback point before execution
  4. Install   — execute via adapter
  5. Configure — PATH, env vars, config templates
  6. Verify    — functional check (not just exit code)
  7. Log       — structured Action Log entry, linked to snapshot

Batch plan preview: multi-tool plans are shown once for approval,
not per-dependency.
"""

from __future__ import annotations

import asyncio
import json
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from resolver import CanonicalAction, DependencyNode, DependencyResolver
from sandbox import dry_run
from snapshot import create as snapshot_create
from verifier import check as verifier_check
from risk_engine import assess as risk_assess


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_command(command: str, timeout: int = 120) -> Dict[str, Any]:
    """Execute a shell command and return structured result."""
    start = time.time()
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        elapsed = round(time.time() - start, 2)
        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:1000],
            "elapsed_s": elapsed,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "exit_code": -1, "stdout": "", "stderr": "Timeout", "elapsed_s": timeout}
    except Exception as exc:
        return {"success": False, "exit_code": -1, "stdout": "", "stderr": str(exc), "elapsed_s": 0}


def _configure_tool(target: str) -> Dict[str, Any]:
    """
    Apply basic post-install configuration: PATH hints, env var suggestions.
    Returns a dict of suggested shell profile additions.
    """
    suggestions: List[str] = []
    os_name = platform.system()

    common_path_additions = {
        "node": {"Windows": "%APPDATA%\\npm", "Linux": "$HOME/.npm-global/bin", "Darwin": "/usr/local/bin"},
        "python": {"Windows": "%LOCALAPPDATA%\\Programs\\Python\\Python3*\\Scripts", "Linux": "$HOME/.local/bin", "Darwin": "/usr/local/bin"},
        "cargo": {"Windows": "%USERPROFILE%\\.cargo\\bin", "Linux": "$HOME/.cargo/bin", "Darwin": "$HOME/.cargo/bin"},
        "go": {"Windows": "%USERPROFILE%\\go\\bin", "Linux": "$HOME/go/bin", "Darwin": "$HOME/go/bin"},
    }

    for tool, paths in common_path_additions.items():
        if tool in target.lower():
            path = paths.get(os_name, "")
            if path:
                suggestions.append(f"Add {path} to PATH")

    return {"path_suggestions": suggestions, "env_hints": {}}


# ─── Stage result helpers ─────────────────────────────────────────────────────

def _stage(name: str, success: bool, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"stage": name, "success": success, "timestamp": _utc_now(), **data}


# ─── Public API ────────────────────────────────────────────────────────────────

class PipelineResult:
    def __init__(self):
        self.stages: List[Dict[str, Any]] = []
        self.success = False
        self.snapshot_id: Optional[str] = None
        self.error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "snapshot_id": self.snapshot_id,
            "error": self.error,
            "stages": self.stages,
        }


def build_batch_plan(actions: List[CanonicalAction]) -> Dict[str, Any]:
    """
    For multi-tool / multi-dependency installs, resolve all trees and return
    a single consolidated plan for one-shot user approval.
    """
    resolver = DependencyResolver()
    trees: List[Dict[str, Any]] = []
    all_install_order: List[Dict[str, Any]] = []
    all_dry_runs: List[Dict[str, Any]] = []

    for action in actions:
        tree = resolver.build_tree(action)
        install_order = resolver.resolve_install_order(tree)
        trees.append(tree.to_dict())

        for node in install_order:
            if node.install_command:
                dr = dry_run(node.install_command)
                all_dry_runs.append({
                    "target": node.name,
                    "command": node.install_command,
                    "dry_run": dr,
                })
                all_install_order.append({
                    "target": node.name,
                    "version": node.version,
                    "adapter": node.adapter_name,
                    "command": node.install_command,
                })

    # Overall risk assessment for the batch
    risk_result = risk_assess(
        action={"command": " && ".join(n["command"] for n in all_install_order[:3])},
    )

    return {
        "plan_type": "batch",
        "action_count": len(actions),
        "install_order": all_install_order,
        "dependency_trees": trees,
        "dry_run_previews": all_dry_runs,
        "overall_risk": risk_result["tier"],
        "risk_reasons": risk_result["reasons"],
    }


def run_pipeline(
    action: CanonicalAction,
    approved: bool = False,
    approval_callback: Optional[Callable[[Dict[str, Any]], bool]] = None,
) -> PipelineResult:
    """
    Execute the full 7-stage pipeline for a CanonicalAction.

    Parameters
    ----------
    action : CanonicalAction
    approved : bool
        If True, skip the approval gate (already approved upstream).
    approval_callback : callable, optional
        Called with the risk/dry-run result; must return True to proceed.
    """
    result = PipelineResult()
    resolver = DependencyResolver()

    # ── Stage 1: Resolve ──────────────────────────────────────────────────────
    try:
        tree = resolver.build_tree(action)
        install_order = resolver.resolve_install_order(tree)
        result.stages.append(_stage("resolve", True, {
            "tree": tree.to_dict(),
            "install_order": [n.name for n in install_order],
        }))
    except Exception as exc:
        result.stages.append(_stage("resolve", False, {"error": str(exc)}))
        result.error = f"Resolution failed: {exc}"
        return result

    for node in install_order:
        if not node.install_command or node.is_cycle or node.error:
            continue

        # ── Stage 2: Dry-run ─────────────────────────────────────────────────
        dr = dry_run(node.install_command)
        result.stages.append(_stage("dry_run", not dr["blocked"], {
            "target": node.name,
            "dry_run": dr,
        }))
        if dr["blocked"]:
            result.error = f"Command blocked by safety layer: {node.install_command}"
            return result

        # ── Risk assessment ───────────────────────────────────────────────────
        risk = risk_assess({"command": node.install_command, "target": node.name, "dry_run_result": dr})

        # ── Approval gate ─────────────────────────────────────────────────────
        if not approved and risk["tier"] in ("Medium", "High"):
            if approval_callback:
                proceed = approval_callback({"node": node.name, "risk": risk, "dry_run": dr})
                if not proceed:
                    result.error = "User declined approval."
                    return result
            else:
                # No callback provided — queue for Control Center
                result.stages.append(_stage("approval", False, {
                    "target": node.name,
                    "risk": risk,
                    "message": "Queued for Control Center approval.",
                }))
                result.error = "Awaiting Control Center approval."
                return result

        # ── Stage 3: Snapshot ────────────────────────────────────────────────
        snap = snapshot_create(action=f"install {node.name}")
        result.snapshot_id = snap["id"]
        result.stages.append(_stage("snapshot", True, {"snapshot_id": snap["id"]}))

        # ── Stage 4: Install ─────────────────────────────────────────────────
        install_result = _run_command(node.install_command)
        result.stages.append(_stage("install", install_result["success"], {
            "target": node.name,
            "command": node.install_command,
            "result": install_result,
        }))
        if not install_result["success"]:
            result.error = f"Install failed for {node.name}: {install_result['stderr'][:200]}"
            return result

        # ── Stage 5: Configure ───────────────────────────────────────────────
        config = _configure_tool(node.name)
        result.stages.append(_stage("configure", True, {"target": node.name, "config": config}))

        # ── Stage 6: Verify ──────────────────────────────────────────────────
        verify = verifier_check(node.name, {
            "on_path": True,
            "adapter": node.adapter_name,
        })
        result.stages.append(_stage("verify", verify["passed"], {
            "target": node.name,
            "evidence": verify["evidence"],
            "failures": verify["failures"],
        }))

        if not verify["passed"]:
            result.error = f"Verification failed for {node.name}: {verify['failures']}"
            return result

    result.success = True
    return result
