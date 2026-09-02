"""
Control Center Routes
=====================
Unified approval queue for ALL pending high-risk/sensitive actions
across every feature. Not scattered per-page.

Endpoints:
  GET  /api/control-center/queue       — list all pending items
  POST /api/control-center/approve     — approve an action
  POST /api/control-center/reject      — reject an action
  GET  /api/control-center/audit       — searchable audit trail
  GET  /api/control-center/trust-tiers — current trust tier config
  POST /api/control-center/trust-tiers — update trust tier
  GET  /api/control-center/snapshots   — list system snapshots
  POST /api/control-center/revert      — revert to snapshot
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import snapshot as snapshot_engine


router = APIRouter(prefix="/api/control-center", tags=["control-center"])

BASE_DIR = Path(__file__).parent
QUEUE_FILE = BASE_DIR / "control_center_queue.json"
AUDIT_FILE = BASE_DIR / "control_center_audit.json"
TRUST_FILE = BASE_DIR / "trust_tiers.json"


# ─── Storage helpers ─────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(path: Path, data: List[Dict[str, Any]], limit: int = 500) -> None:
    path.write_text(json.dumps(data[-limit:], indent=2), encoding="utf-8")


def _load_trust() -> Dict[str, Any]:
    if not TRUST_FILE.exists():
        return {}
    try:
        return json.loads(TRUST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_trust(data: Dict[str, Any]) -> None:
    TRUST_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ─── Pydantic models ─────────────────────────────────────────────────────────

class EnqueueRequest(BaseModel):
    action_id: Optional[str] = None
    command: str
    target: str
    risk_tier: str  # Low | Medium | High
    risk_reasons: List[str] = []
    dry_run_preview: Dict[str, Any] = {}
    dependency_tree: Dict[str, Any] = {}
    snapshot_id: Optional[str] = None
    source: str = "pipeline"  # pipeline | repair | driver | terminal


class DecisionRequest(BaseModel):
    action_id: str
    reason: Optional[str] = None


class TrustTierUpdate(BaseModel):
    category: str  # e.g. 'cleanup', 'driver_update'
    level: str     # 'always_allow' | 'always_require_approval' | 'default'


# ─── Queue management ─────────────────────────────────────────────────────────

@router.post("/enqueue")
async def enqueue_action(req: EnqueueRequest) -> Dict[str, Any]:
    """Add an action to the approval queue (called internally by pipeline/agent)."""
    queue = _load(QUEUE_FILE)
    action_id = req.action_id or str(uuid.uuid4())[:8]
    item = {
        "action_id": action_id,
        "status": "pending",
        "enqueued_at": _utc_now(),
        "command": req.command,
        "target": req.target,
        "risk_tier": req.risk_tier,
        "risk_reasons": req.risk_reasons,
        "dry_run_preview": req.dry_run_preview,
        "dependency_tree": req.dependency_tree,
        "snapshot_id": req.snapshot_id,
        "source": req.source,
    }
    queue.append(item)
    _save(QUEUE_FILE, queue)
    return {"ok": True, "action_id": action_id}


@router.get("/queue")
async def get_queue(
    status: Optional[str] = Query(None, description="Filter by status: pending|approved|rejected"),
    risk: Optional[str] = Query(None, description="Filter by risk tier: Low|Medium|High"),
) -> Dict[str, Any]:
    """Return all queued actions, optionally filtered."""
    queue = _load(QUEUE_FILE)
    if status:
        queue = [q for q in queue if q.get("status") == status]
    if risk:
        queue = [q for q in queue if q.get("risk_tier") == risk]
    return {"ok": True, "items": list(reversed(queue)), "total": len(queue)}


@router.post("/approve")
async def approve_action(req: DecisionRequest) -> Dict[str, Any]:
    """Approve a pending action."""
    queue = _load(QUEUE_FILE)
    audit = _load(AUDIT_FILE)

    item = next((q for q in queue if q["action_id"] == req.action_id), None)
    if not item:
        raise HTTPException(status_code=404, detail=f"Action {req.action_id} not found in queue")
    if item["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Action already {item['status']}")

    item["status"] = "approved"
    item["decided_at"] = _utc_now()
    item["reason"] = req.reason or ""
    _save(QUEUE_FILE, queue)

    audit.append({**item, "decision": "approved"})
    _save(AUDIT_FILE, audit)

    return {"ok": True, "action_id": req.action_id, "status": "approved"}


@router.post("/reject")
async def reject_action(req: DecisionRequest) -> Dict[str, Any]:
    """Reject a pending action."""
    queue = _load(QUEUE_FILE)
    audit = _load(AUDIT_FILE)

    item = next((q for q in queue if q["action_id"] == req.action_id), None)
    if not item:
        raise HTTPException(status_code=404, detail=f"Action {req.action_id} not found in queue")
    if item["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Action already {item['status']}")

    item["status"] = "rejected"
    item["decided_at"] = _utc_now()
    item["reason"] = req.reason or ""
    _save(QUEUE_FILE, queue)

    audit.append({**item, "decision": "rejected"})
    _save(AUDIT_FILE, audit)

    return {"ok": True, "action_id": req.action_id, "status": "rejected"}


# ─── Audit trail ──────────────────────────────────────────────────────────────

@router.get("/audit")
async def get_audit(
    search: Optional[str] = Query(None),
    decision: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
) -> Dict[str, Any]:
    """Searchable, filterable audit trail."""
    audit = _load(AUDIT_FILE)
    if decision:
        audit = [a for a in audit if a.get("decision") == decision]
    if source:
        audit = [a for a in audit if a.get("source") == source]
    if search:
        q = search.lower()
        audit = [
            a for a in audit
            if q in a.get("target", "").lower()
            or q in a.get("command", "").lower()
        ]
    return {"ok": True, "entries": list(reversed(audit))[-limit:], "total": len(audit)}


# ─── Trust tiers ─────────────────────────────────────────────────────────────

@router.get("/trust-tiers")
async def get_trust_tiers() -> Dict[str, Any]:
    return {"ok": True, "tiers": _load_trust()}


@router.post("/trust-tiers")
async def set_trust_tier(req: TrustTierUpdate) -> Dict[str, Any]:
    tiers = _load_trust()
    tiers[req.category] = req.level
    _save_trust(tiers)
    return {"ok": True, "category": req.category, "level": req.level}


# ─── Snapshots ────────────────────────────────────────────────────────────────

@router.get("/snapshots")
async def list_snapshots() -> Dict[str, Any]:
    snaps = snapshot_engine.list_snapshots()
    return {"ok": True, "snapshots": snaps}


class RevertRequest(BaseModel):
    snapshot_id: str


@router.post("/revert")
async def revert_snapshot(req: RevertRequest) -> Dict[str, Any]:
    result = snapshot_engine.revert(req.snapshot_id)
    return {"ok": result["success"], **result}
