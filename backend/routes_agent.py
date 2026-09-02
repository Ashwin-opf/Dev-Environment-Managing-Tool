"""
Agent Orchestrator Routes
=========================
Exposes the agent orchestrator via HTTP so the frontend can:
  - Run a high-level goal through the agent
  - Get the current session's reasoning trail
  - Get previous session logs
  - Inspect the 12 individual agent tools directly
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent_orchestrator import AgentOrchestrator

router = APIRouter(prefix="/api/agent", tags=["agent"])

BASE_DIR = Path(__file__).parent
REASONING_LOG_FILE = BASE_DIR / "agent_reasoning_log.jsonl"


class GoalRequest(BaseModel):
    goal: str
    auto_approve_low_risk: bool = True


class ToolCallRequest(BaseModel):
    tool: str
    params: Dict[str, Any] = {}


@router.post("/run")
async def run_goal(req: GoalRequest) -> Dict[str, Any]:
    """
    Run a high-level goal through the agent orchestrator.
    Example: {"goal": "install git and node"}
    """

    def _auto_approval(context: Dict[str, Any]) -> bool:
        """Auto-approve low/medium risk if enabled, else queue."""
        if req.auto_approve_low_risk:
            tier = context.get("risk", {}).get("tier", "High")
            return tier in ("Low", "Medium")
        return False

    try:
        orchestrator = AgentOrchestrator(approval_callback=_auto_approval)
        result = orchestrator.run(req.goal)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/tool")
async def call_tool(req: ToolCallRequest) -> Dict[str, Any]:
    """
    Call a single agent tool directly for debugging / testing.
    tool names: resolver_build_tree, adapter_resolve_latest, sandbox_dry_run,
                snapshot_create, snapshot_revert, verifier_check, kb_retrieve,
                kb_write, model_propose_fix, risk_assess, approval_request
    """
    orchestrator = AgentOrchestrator()
    tool_map = {
        "resolver_build_tree":    orchestrator.tool_resolver_build_tree,
        "adapter_resolve_latest": orchestrator.tool_adapter_resolve_latest,
        "adapter_install":        orchestrator.tool_adapter_install,
        "adapter_remove":         orchestrator.tool_adapter_remove,
        "sandbox_dry_run":        orchestrator.tool_sandbox_dry_run,
        "snapshot_create":        orchestrator.tool_snapshot_create,
        "snapshot_revert":        orchestrator.tool_snapshot_revert,
        "executor_run":           orchestrator.tool_executor_run,
        "verifier_check":         orchestrator.tool_verifier_check,
        "kb_retrieve":            orchestrator.tool_kb_retrieve,
        "kb_write":               orchestrator.tool_kb_write,
        "model_propose_fix":      orchestrator.tool_model_propose_fix,
        "risk_assess":            orchestrator.tool_risk_assess,
    }

    fn = tool_map.get(req.tool)
    if not fn:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {req.tool}. Valid: {list(tool_map)}")

    try:
        result = fn(**req.params)
        return {"ok": True, "tool": req.tool, "result": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/sessions")
async def list_sessions(limit: int = 20) -> Dict[str, Any]:
    """Return recent agent session summaries from the reasoning log."""
    if not REASONING_LOG_FILE.exists():
        return {"ok": True, "sessions": []}
    sessions = []
    try:
        lines = REASONING_LOG_FILE.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines[-limit:]):
            try:
                data = json.loads(line)
                sessions.append({
                    "session_id": data.get("session_id"),
                    "goal": data.get("goal"),
                    "completed": data.get("completed", []),
                    "failed": data.get("failed", []),
                    "timestamp": data.get("timestamp"),
                    "trail_steps": len(data.get("trail", [])),
                })
            except Exception:
                pass
    except Exception:
        pass
    return {"ok": True, "sessions": sessions}


@router.get("/sessions/{session_id}/trail")
async def get_reasoning_trail(session_id: str) -> Dict[str, Any]:
    """Return the full reasoning trail for a specific session."""
    if not REASONING_LOG_FILE.exists():
        raise HTTPException(status_code=404, detail="No session logs found")
    try:
        for line in REASONING_LOG_FILE.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
                if data.get("session_id") == session_id:
                    return {"ok": True, "session": data}
            except Exception:
                pass
    except Exception:
        pass
    raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
