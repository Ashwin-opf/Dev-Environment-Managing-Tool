import json
from typing import Any
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

from logger import get_log_file, clear_logs, log_action, export_logs_text

router = APIRouter()


class LogDeleteRequest(BaseModel):
    confirm: bool = False
    all: bool = False
    indices: list[int] = []


def _parse_log_entries(limit: int = 200) -> list[dict[str, Any]]:
    log_file = get_log_file()
    if not log_file.exists():
        return []
    entries: list[dict[str, Any]] = []
    raw_lines = log_file.read_text(encoding="utf-8").splitlines()
    start_idx = max(0, len(raw_lines) - limit)
    for idx in range(start_idx, len(raw_lines)):
        line = raw_lines[idx].strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            if payload.get("action") in ("STARTUP", "LOGS_CLEARED", "LOGS_DELETED") or "initialized" in payload.get("friendly_summary", "").lower() or "initialized" in payload.get("detail", "").lower():
                continue
            payload["_raw"] = raw_lines[idx]
            payload["_file_line_idx"] = idx
            entries.append(payload)
        except json.JSONDecodeError:
            if "initialized" in line.lower():
                continue
            import datetime
            ts = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
            entries.append({
                "timestamp": ts,
                "action": "LOG",
                "command": line,
                "detail": line,
                "friendly_summary": line,
                "_raw": raw_lines[idx],
                "_file_line_idx": idx
            })
    entries.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return entries


@router.get("/api/logs")
async def get_logs():
    entries = _parse_log_entries(200)
    
    # Enrich log entries with self-healing DB lookup
    import sqlite3
    from self_healing import DB_PATH
    
    enriched = []
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT result, fix_source, timestamp, cause, attempted_fix, safety_class, validation_result, error_message
            FROM self_healing_attempts
            WHERE archived = 0
            ORDER BY timestamp DESC
        """)
        rows = cur.fetchall()
        conn.close()
        
        for entry in entries[:100]:
            cmd = entry.get("command", "")
            action = entry.get("action", "")
            if action in ("FAILED", "BLOCKED") or "error" in entry.get("detail", "").lower():
                detail = entry.get("detail", "")
                matched_row = None
                for row in rows:
                    if row[4] == cmd:
                        matched_row = row
                        break
                    if detail and row[7] and detail in row[7]:
                        matched_row = row
                        break
                
                if matched_row:
                    entry["self_healing"] = {
                        "status": matched_row[0],
                        "source": matched_row[1],
                        "timestamp": matched_row[2],
                        "cause": matched_row[3],
                        "attempted_fix": matched_row[4],
                        "safety_class": matched_row[5],
                        "validation_result": matched_row[6]
                    }
                else:
                    entry["self_healing"] = {
                        "status": "Waiting User Approval" if action == "BLOCKED" else "Learning",
                        "source": "Local System Rules",
                        "timestamp": entry.get("timestamp"),
                        "cause": entry.get("detail", "Safety block or execution error"),
                        "attempted_fix": cmd,
                        "safety_class": "Caution" if action == "FAILED" else "Blocked",
                        "validation_result": "Passed"
                    }
            enriched.append(entry)
    except Exception:
        enriched = entries[:100]
        
    return {"ok": True, "logs": enriched, "count": len(enriched)}


@router.delete("/api/logs")
async def delete_all_logs(confirm: bool = False):
    if not confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to delete all logs.")
    removed = clear_logs()
    
    # Archive instead of delete
    try:
        import sqlite3
        from self_healing import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE self_healing_attempts SET archived = 1")
            conn.commit()
    except Exception:
        pass
        
    log_action("LOGS_CLEARED", "", f"Removed {removed} entries", friendly_summary="All logs cleared")
    return {"ok": True, "removed": removed}


@router.post("/api/logs/clear")
async def clear_logs_endpoint(body: dict = Body(default={})):
    if not body.get("confirm"):
        raise HTTPException(status_code=400, detail="Confirmation required to clear logs.")
    removed = clear_logs()
    
    # Archive instead of delete
    try:
        import sqlite3
        from self_healing import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE self_healing_attempts SET archived = 1")
            conn.commit()
    except Exception:
        pass
        
    log_action("LOGS_CLEARED", "", f"Removed {removed} entries", friendly_summary="Logs cleared from Control Center")
    return {"ok": True, "removed": removed}


@router.post("/api/logs/delete")
async def delete_logs_endpoint(req: LogDeleteRequest):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required to delete logs.")
    if req.all:
        removed = clear_logs()
        # Archive instead of delete
        try:
            import sqlite3
            from self_healing import DB_PATH
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("UPDATE self_healing_attempts SET archived = 1")
                conn.commit()
        except Exception:
            pass
    else:
        from logger import _read_log_lines, _write_log_lines

        entries = _parse_log_entries(500)
        indices_to_remove = set()
        for idx in req.indices:
            if 0 <= idx < len(entries):
                indices_to_remove.add(entries[idx]["_file_line_idx"])
                
        all_lines = _read_log_lines()
        new_lines = [all_lines[i] for i in range(len(all_lines)) if i not in indices_to_remove]
        removed = len(all_lines) - len(new_lines)
        _write_log_lines(new_lines)
    log_action("LOGS_DELETED", "", f"Removed {removed} entries", friendly_summary="Logs deleted")
    return {"ok": True, "removed": removed}


@router.get("/api/logs/export")
async def export_logs():
    text = export_logs_text()
    return {"ok": True, "content": text, "filename": "pc_doctor_logs.txt"}
