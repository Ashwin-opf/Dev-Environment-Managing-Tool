"""
test_lab/verifier.py — Authoritative, independent verification system for Test Lab.

Implements the multi-level verification contract:
- L1: Persistent state mutation completed (direct registry / system probe).
- L2: Executable launches and returns valid version.
- L3: Fresh process spawned with reconstructed environment resolves exact binary (e.g. where.exe).
- L5: Original problem rescanned and confirmed resolved.
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Any, Dict, Tuple
from test_lab.models import FaultDefinition
from dev_environment_detector import EffectivePath, dev_environment_detector, canonical_store, ToolHealthStatus


class FaultVerifier:
    """Independent verification engine that does not rely on repair engine status."""

    @classmethod
    def verify_repair(
        cls, fault_def: FaultDefinition, expected_dir: Optional[str] = None
    ) -> Tuple[bool, Dict[str, bool], str]:
        """
        Executes L1, L2, L3, and L5 verification levels.
        Returns: (all_passed, {L1: bool, L2: bool, L3: bool, L5: bool}, summary_message)
        """
        levels = {"L1": False, "L2": False, "L3": False, "L5": False}
        target_dir = expected_dir or fault_def.target_entry or ""
        target_name = fault_def.target

        # ── Level 1: Persistent State Mutation ──────────────────────────────
        if fault_def.capability.value == "PATH":
            scope = (fault_def.scope or "MACHINE").upper()
            persistent_entries = (
                EffectivePath.get_machine_path() if scope == "MACHINE" else EffectivePath.get_user_path()
            )
            target_norm = EffectivePath.normalize_path_entry(target_dir)
            levels["L1"] = any(EffectivePath.normalize_path_entry(p) == target_norm for p in persistent_entries)
        elif fault_def.capability.value == "SERVICE":
            svc_name = fault_def.metadata.get("service_name", target_name)
            info = dev_environment_detector.check_service(svc_name)
            levels["L1"] = info.get("status") == "Running"
        elif fault_def.capability.value == "PORT":
            port = fault_def.metadata.get("port", 18765)
            levels["L1"] = not dev_environment_detector.check_port(port)
        else:
            levels["L1"] = True

        # ── Level 2: Executable Version Launch ──────────────────────────────
        ident = canonical_store.resolve(target_name)
        if ident and ident.executable:
            binary_candidates = dev_environment_detector.discover_executable(ident)
            if binary_candidates:
                ver_out, launch_ok = dev_environment_detector._test_launch_in_persistent_env(
                    ident, binary_candidates[0]
                )
                levels["L2"] = launch_ok and bool(ver_out)
            else:
                levels["L2"] = False
        else:
            levels["L2"] = True

        # ── Level 3: Fresh Process Environment Reconstruction ───────────────
        if platform.system() == "Windows" and ident and ident.executable:
            try:
                # Construct fresh environment dictionary strictly from persistent registry
                fresh_env = os.environ.copy()
                fresh_env["PATH"] = ";".join(EffectivePath.get_effective_persistent_path())
                proc = subprocess.run(
                    ["where.exe", ident.executable_name],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=fresh_env,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    found_lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
                    if target_dir:
                        norm_target = EffectivePath.normalize_path_entry(target_dir)
                        levels["L3"] = any(norm_target in EffectivePath.normalize_path_entry(l) for l in found_lines)
                    else:
                        levels["L3"] = len(found_lines) > 0
            except Exception:
                levels["L3"] = False
        else:
            levels["L3"] = True

        # ── Level 5: Rescan and Problem Clearance ───────────────────────────
        if ident:
            diag = dev_environment_detector.diagnose_tool(ident)
            levels["L5"] = diag.status == ToolHealthStatus.INSTALLED_AND_USABLE or (
                diag.status == ToolHealthStatus.SERVICE_INSTALLED_BUT_STOPPED and levels["L1"]
            )
        else:
            levels["L5"] = levels["L1"]

        all_passed = all(levels.values())
        msg = (
            f"Independent verification passed (L1={levels['L1']}, L2={levels['L2']}, L3={levels['L3']}, L5={levels['L5']})"
            if all_passed
            else f"Independent verification incomplete: {levels}"
        )
        return all_passed, levels, msg

    def verify_l1_l5(
        self,
        target_identity: str,
        capability: FaultCapability,
        expected_entry: Optional[str] = None,
        scope: str = "MACHINE",
        mock_mode: bool = False,
    ) -> Dict[str, bool]:
        """Convenience method returning L1-L5 levels dictionary."""
        if mock_mode:
            return {"L1": True, "L2": True, "L3": True, "L5": True}
        fault_def = FaultDefinition(
            fault_id=f"VERIFY_{target_identity}",
            target=target_identity,
            capability=capability,
            scope=scope,
            target_entry=expected_entry,
        )
        _, levels, _ = self.verify_repair(fault_def, expected_dir=expected_entry)
        return levels


fault_verifier = FaultVerifier()

