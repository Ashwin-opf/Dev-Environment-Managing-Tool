"""
SHCE API Routes – /api/shce/*
Provides the full Self-Healing Core Engine Control Center API.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shce_engine import shce, mutation_engine, error_intelligence_db, env_profiler, DB_PATH
from shce_engine import PackageVerifier, PackageKnowledgeStore, EnvironmentProfiler
from pathlib import Path
from repair_engine import RepairCommandManager

_repair_cmd_manager = RepairCommandManager(Path(DB_PATH))

router = APIRouter()


# ─── Pydantic models ──────────────────────────────────────────────────────────
class VerifyPackageRequest(BaseModel):
    package_name: str


class QueueFromErrorRequest(BaseModel):
    custom_command: Optional[str] = None


class PackageKnowledgeRecord(BaseModel):
    package_name: str
    install_method: str = "apt"
    repository_required: Optional[str] = None
    verification_status: str = "verified"
    fallback_methods: Optional[str] = None

class MutateRequest(BaseModel):
    command: str
    error: str
    max_results: int = 5


class ApproveQueueRequest(BaseModel):
    confirm_dangerous: bool = False


class RejectQueueRequest(BaseModel):
    reason: str = ""


class LearnRequest(BaseModel):
    os_name: str
    error_pattern: str
    successful_fix: str
    source: str = "Manual"
    success: bool = True


class DeleteKnowledgeRequest(BaseModel):
    entry_id: int


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/api/shce/status")
def shce_status():
    """SHCE core status — health score, queue depth, last fix."""
    try:
        data = shce.get_dashboard_data()
        return {
            "ok": True,
            "status": data["status"],
            "environment": {
                "os_label": data["environment"].get("os_label"),
                "package_manager": data["environment"].get("package_manager"),
                "network_online": data["environment"].get("network_online"),
                "ollama_running": data["environment"].get("ollama_running"),
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/shce/dashboard")
def shce_dashboard():
    """Full SHCE Control Center dashboard payload."""
    try:
        return shce.get_dashboard_data()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/shce/environment")
def shce_environment():
    """Real-time environment snapshot."""
    try:
        return {"ok": True, "environment": env_profiler.snapshot()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/shce/error-log")
def shce_error_log(limit: int = 50, offset: int = 0):
    """Paginated error intelligence log."""
    try:
        entries = error_intelligence_db.get_error_log(limit=limit, offset=offset)
        total = error_intelligence_db.get_error_count()
        return {"ok": True, "entries": entries, "total": total}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/shce/knowledge")
def shce_knowledge():
    """Adaptive knowledge base entries."""
    try:
        kb = shce._kb_stats()
        return {"ok": True, **kb}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/shce/queue")
def shce_queue(status: Optional[str] = None, limit: int = 50):
    """SHCE repair queue."""
    try:
        items = error_intelligence_db.get_queue(status=status, limit=limit)
        return {"ok": True, "queue": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/shce/mutate")
def shce_mutate(req: MutateRequest):
    """
    Generate alternative commands for a failed command + error.
    Returns ranked candidates with safety classification.
    """
    try:
        candidates = mutation_engine.generate_alternatives(
            req.command, req.error, max_results=req.max_results
        )
        return {"ok": True, "candidates": candidates, "count": len(candidates)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/shce/handle-failure")
def shce_handle_failure(req: MutateRequest):
    """
    Full pipeline: log error, generate candidates, enqueue best.
    Called automatically by repair_engine after any failed command.
    """
    try:
        result = shce.handle_failure(
            command=req.command,
            error=req.error,
            source="repair_engine",
            auto_queue=True,
        )
        return {"ok": True, **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/shce/approve/{queue_id}")
def shce_approve(queue_id: int, req: ApproveQueueRequest = ApproveQueueRequest()):
    """
    Approve and execute a SHCE queued fix.
    Dangerous commands require confirm_dangerous=true.
    """
    from self_healing import SafetyClassificationLayer

    item = error_intelligence_db.get_queue_item(queue_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

    cmd = item.get("selected_candidate", "")
    if not cmd:
        raise HTTPException(status_code=400, detail="No command selected for this item")

    safety_class = SafetyClassificationLayer.classify(cmd)
    if safety_class == "Blocked":
        raise HTTPException(status_code=400, detail="Command blocked by safety layer")
    if safety_class == "Dangerous" and not req.confirm_dangerous:
        return {
            "ok": False,
            "requires_secondary_confirmation": True,
            "message": f"Command classified as DANGEROUS: '{cmd}'. Send confirm_dangerous=true to proceed.",
        }

    result = shce.execute_queued_fix(queue_id)
    return result


@router.post("/api/shce/reject/{queue_id}")
def shce_reject(queue_id: int, req: RejectQueueRequest = RejectQueueRequest()):
    """Reject and dismiss a queued fix."""
    item = error_intelligence_db.get_queue_item(queue_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")
    if item.get("status") == "executing":
        raise HTTPException(status_code=400, detail="Cannot reject a queue item that is currently healing/executing")
    error_intelligence_db.update_queue_item(queue_id, "rejected", stderr=req.reason, rc=-1)
    return {"ok": True, "message": "Fix rejected and removed from queue"}


@router.post("/api/shce/learn")
def shce_learn(req: LearnRequest):
    """Manually feed a successful fix into the adaptive knowledge base."""
    try:
        from self_healing import self_healing_mgr
        import platform
        self_healing_mgr.record_knowledge(
            os_name=req.os_name or platform.system(),
            os_version="",
            kernel_version=platform.release(),
            error_pattern=req.error_pattern,
            successful_fix=req.successful_fix,
            default_fallback="",
            source=req.source,
            success=req.success,
        )
        return {"ok": True, "message": "Fix recorded in knowledge base"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/api/shce/knowledge/{entry_id}")
def shce_delete_knowledge(entry_id: int):
    """Remove an entry from the adaptive knowledge base."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM adaptive_knowledge_base WHERE id = ?", (entry_id,))
        affected = cur.rowcount
        conn.commit()
        conn.close()
        if affected == 0:
            raise HTTPException(status_code=404, detail=f"Knowledge entry {entry_id} not found")
        return {"ok": True, "message": f"Entry {entry_id} deleted"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/api/shce/error-log/bulk-resolved")
def shce_delete_bulk_resolved():
    """Remove ALL entries from the error intelligence log (including pending/no-candidate).

    Clears every row in error_intelligence.  Returns {"ok": true, "removed": <count>}
    on success or {"ok": false, "error": "<message>"} on failure.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM error_intelligence")
        removed = cur.rowcount
        conn.commit()
        conn.close()
        return {"ok": True, "removed": removed}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


class UpdateQueueCommandRequest(BaseModel):
    command: str


@router.patch("/api/shce/queue/{queue_id}/command")
def shce_update_queue_command(queue_id: int, req: UpdateQueueCommandRequest):
    """Update the selected_candidate command for a queued fix before approval."""
    if not req.command or not req.command.strip():
        raise HTTPException(status_code=400, detail="Command cannot be empty")
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "UPDATE shce_queue SET selected_candidate = ? WHERE id = ? AND status = 'pending'",
            (req.command.strip(), queue_id)
        )
        affected = cur.rowcount
        conn.commit()
        conn.close()
        if affected == 0:
            raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found or not pending")
        return {"ok": True, "message": f"Command updated for queue item {queue_id}"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/api/shce/queue/{error_id}/command")
def shce_put_queue_command(error_id: int, req: UpdateQueueCommandRequest):
    """
    Update the selected_candidate command for a pending queue item via
    RepairCommandManager — the single source of truth for command sync.

    This endpoint is the primary path used by the Repair Queue UI when
    a user edits a command.  Only pending items may be updated.
    """
    try:
        updated = _repair_cmd_manager.update_command(str(error_id), req.command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if not updated:
        raise HTTPException(
            status_code=404,
            detail=f"Queue item {error_id} not found or is not in pending state",
        )
    return {"ok": True, "message": f"Command updated for queue item {error_id}"}


@router.get("/api/shce/queue/{error_id}/command")
def shce_get_queue_command(error_id: int):
    """
    Retrieve the current selected_candidate command for a queue item via
    RepairCommandManager.  Used by the UI to display the authoritative
    command before approval.
    """
    try:
        command = _repair_cmd_manager.get_display_command(str(error_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if command is None:
        raise HTTPException(status_code=404, detail=f"Queue item {error_id} not found")
    return {"ok": True, "error_id": error_id, "command": command}


@router.delete("/api/shce/error-log/{entry_id}")
def shce_delete_error_log(entry_id: int):
    """Remove any entry from the error intelligence log (including pending/no-candidate)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT id FROM error_intelligence WHERE id = ?", (entry_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Error log {entry_id} not found")
        cur.execute("DELETE FROM error_intelligence WHERE id = ?", (entry_id,))
        conn.commit()
        conn.close()
        return {"ok": True, "message": f"Error log {entry_id} deleted"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/api/shce/queue/{queue_id}")
def shce_delete_queue_item(queue_id: int):
    """Remove a non-pending entry from the SHCE queue (history)."""
    item = error_intelligence_db.get_queue_item(queue_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")
    if item["status"] == "pending":
        raise HTTPException(status_code=400, detail="Cannot delete pending queue items")
    if item.get("status") == "executing":
        raise HTTPException(status_code=400, detail="Cannot delete queue items that are currently healing/executing")
    error_intelligence_db.delete_queue_item(queue_id)
    return {"ok": True, "message": f"Queue item {queue_id} deleted"}


@router.post("/api/shce/queue-from-error/{error_id}")
def shce_queue_from_error(error_id: int, req: Optional[QueueFromErrorRequest] = None):
    """
    Promote an error log entry's best candidate into the Repair Queue, or
    enqueue a custom user-defined fix command.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, command, error_raw, candidates FROM error_intelligence WHERE id = ?",
            (error_id,)
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail=f"Error log {error_id} not found")

        custom_cmd = req.custom_command.strip() if (req and req.custom_command) else None

        raw_candidates = row["candidates"] or "[]"
        try:
            candidates: List[Dict[str, Any]] = json.loads(raw_candidates)
        except (json.JSONDecodeError, ValueError):
            candidates = []

        if custom_cmd:
            best_cmd = custom_cmd
        else:
            if not candidates:
                raise HTTPException(
                    status_code=400,
                    detail="No repair candidates available for this error log entry."
                )
            best = candidates[0]
            best_cmd = best.get("command", "").strip()

        if not best_cmd:
            raise HTTPException(status_code=400, detail="Best candidate or custom command has no command text.")

        queue_id = error_intelligence_db.enqueue(
            command=row["command"],
            error=row["error_raw"] or "",
            selected_candidate=best_cmd,
            candidates=candidates,
        )
        # Delete from error monitor since it has been moved to repair queue
        try:
            error_intelligence_db.delete_error(error_id)
        except Exception:
            pass
        return {
            "ok": True,
            "queue_id": queue_id,
            "command": best_cmd,
            "message": f"Fix queued as Repair Queue item #{queue_id}. Switch to Repair Queue to approve.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))



# ─── Package Verification Endpoints ──────────────────────────────────────────

@router.post("/api/shce/verify-package")
def shce_verify_package(req: VerifyPackageRequest):
    """
    Run the full 5-source verification pipeline for a package name.
    Returns a structured VerificationResult with a user-friendly message string
    (no raw JSON curly braces shown to the user).
    """
    if not req.package_name or not req.package_name.strip():
        raise HTTPException(status_code=400, detail="package_name must not be empty or whitespace")
    try:
        env = EnvironmentProfiler.snapshot()
        online = env.get("network_online", False)
        verifier = PackageVerifier()
        result = verifier.verify(req.package_name, online=online)
        d = result.to_dict()

        # Build a user-friendly prose message instead of raw JSON
        pkg = d.get("package", req.package_name)
        confidence = d.get("confidence", 0)
        verified = d.get("verified", False)
        source = d.get("verification_source", "none")
        command = d.get("command")
        reason = d.get("reason", "")
        suggestion = d.get("suggestion")

        if verified and command:
            message = (
                f"{pkg}: Verified ({confidence}% confidence via {source}). "
                f"Install command: {command}"
            )
        elif suggestion:
            message = (
                f"{pkg}: Could not be verified. "
                f"Did you mean '{suggestion}'? "
                f"Confidence: {confidence}%. "
                f"No installation command generated."
            )
        elif not online and confidence == 0:
            message = (
                f"{pkg}: No verified installation method available offline. "
                f"Confidence: {confidence}%."
            )
        else:
            message = (
                f"{pkg}: No verified installation method found. "
                f"Confidence: {confidence}%. "
                f"{reason or 'Package not found in any known source.'}"
            )

        return {"ok": True, "message": message, **d}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/shce/package-knowledge")
def shce_get_package_knowledge(limit: int = 100, offset: int = 0):
    """
    Return a paginated list of all entries in the Package Knowledge Store.
    Query params: limit (default 100), offset (default 0).
    """
    try:
        if limit < 1 or limit > 500:
            limit = 100
        pks = PackageKnowledgeStore()
        items = pks.list_all(limit=limit, offset=offset)
        total = pks.count()
        return {"ok": True, "total": total, "items": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/shce/package-knowledge")
def shce_upsert_package_knowledge(req: PackageKnowledgeRecord):
    """
    Manually add or update a package record in the Package Knowledge Store.
    Performs an upsert (insert or replace) keyed on package_name.
    """
    if not req.package_name or not req.package_name.strip():
        raise HTTPException(status_code=400, detail="package_name must not be empty")
    try:
        pks = PackageKnowledgeStore()
        pks.upsert(
            req.package_name.strip().lower(),
            install_method=req.install_method,
            repository_required=req.repository_required,
            verification_status=req.verification_status,
            fallback_methods=req.fallback_methods,
        )
        return {"ok": True, "package_name": req.package_name.strip().lower()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
