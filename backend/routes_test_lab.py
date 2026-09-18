"""
routes_test_lab.py — FastAPI endpoints for the PC Doctor Fault Injection / Test Lab.

Strictly development-only API protected by SafetyGuard.
All routes return 403 Forbidden in production environments.
"""

from __future__ import annotations

import logging
import platform
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from fastapi import APIRouter, HTTPException, Depends

from test_lab.models import FaultDefinition, TestResult
from test_lab.safety_guard import SafetyGuard, is_fault_injection_enabled
from test_lab.catalog import fault_catalog
from test_lab.baseline_manager import baseline_manager
from test_lab.test_runner import test_runner
from test_lab.solvability_report import solvability_reporter

logger = logging.getLogger("pc_doctor.routes_test_lab")


def require_dev_mode():
    """Dependency ensuring test lab endpoints are only accessible in development mode."""
    allowed, reason = SafetyGuard.check_environment()
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=f"PC Doctor Fault Injection / Test Lab is disabled in production: {reason}",
        )


router = APIRouter(
    prefix="/api/test-lab",
    tags=["test-lab"],
    dependencies=[Depends(require_dev_mode)],
)


class RunTestRequest(BaseModel):
    fault_id: str
    confirm_mutation: bool = False
    custom_target_entry: Optional[str] = None


@router.get("/status")
async def get_test_lab_status() -> Dict[str, Any]:
    """
    Get current test lab environment, active baselines, and safety state.
    """
    enabled, reason = SafetyGuard.check_environment()
    pending = baseline_manager.list_pending()
    
    return {
        "ok": True,
        "enabled": enabled,
        "reason": reason,
        "platform": platform.system().lower(),
        "pending_baselines_count": len(pending),
        "pending_baselines": [b.to_dict() for b in pending],
        "active_tests_count": len(test_runner.get_active_tests()),
        "active_tests": test_runner.get_active_tests(),
    }


@router.get("/faults")
async def list_faults(
    platform_name: Optional[str] = None,
    capability: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List all registered fault definitions in the catalog.
    """
    faults = fault_catalog.list_all(platform=platform_name, capability=capability)
    return {
        "ok": True,
        "count": len(faults),
        "faults": [f.to_dict() for f in faults],
    }


@router.get("/faults/{fault_id}")
async def get_fault(fault_id: str) -> Dict[str, Any]:
    """
    Get a specific fault definition by ID.
    """
    fault = fault_catalog.get(fault_id)
    if not fault:
        raise HTTPException(status_code=404, detail=f"Fault '{fault_id}' not found in catalog.")
    return {
        "ok": True,
        "fault": fault.to_dict(),
    }


@router.post("/run")
async def run_fault_test(req: RunTestRequest) -> Dict[str, Any]:
    """
    Execute an end-to-end fault test:
    Baseline Capture → Injection → Fault Verification → PC Doctor Pipeline →
    Independent Verification → Baseline Restoration → Test Solvability Recording.
    """
    fault = fault_catalog.get(req.fault_id)
    if not fault:
        raise HTTPException(status_code=404, detail=f"Fault '{req.fault_id}' not found in catalog.")

    # Enforce confirmation for real-machine mutation
    if fault.simulation_mode.value == "REAL" and not req.confirm_mutation:
        raise HTTPException(
            status_code=400,
            detail=(
                "Explicit confirmation required: This test intentionally changes a controlled "
                "system state. The original state will be captured and restored after testing."
            ),
        )

    try:
        result: TestResult = await test_runner.run_test(
            fault_def=fault,
            confirm_mutation=req.confirm_mutation,
            custom_target_entry=req.custom_target_entry,
        )
        solvability_reporter.record_result(result)
        res_dict = result.to_dict()
        res_dict["ok"] = True
        return res_dict
    except Exception as e:
        logger.exception("Unexpected error executing fault test: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restore-all")
async def restore_all_pending() -> Dict[str, Any]:
    """
    Fail-safe emergency recovery: restores all pending captured baselines.
    """
    results = await test_runner.restore_all_pending()
    return {
        "ok": True,
        "restored_count": len(results),
        "results": results,
    }


@router.get("/report")
async def get_solvability_report() -> Dict[str, Any]:
    """
    Generate the authoritative Solvability & Health Report for tested faults.
    """
    report = solvability_reporter.generate_report()
    return {
        "ok": True,
        "report": report,
    }


@router.post("/report/clear")
async def clear_solvability_report() -> Dict[str, Any]:
    """
    Clear historical test lab results.
    """
    solvability_reporter.clear_history()
    return {
        "ok": True,
        "message": "Test lab history cleared.",
    }
