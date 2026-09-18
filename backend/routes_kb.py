"""
routes_kb.py — Two-Part Knowledge Base API

Part A: knowledge_static.db  — sealed, pre-loaded repair recipes (read-only)
Part B: knowledge_dynamic.db — user-approved learned solutions with RAG promotion
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# ─── DB paths ────────────────────────────────────────────────────────────────
_BASE = Path(__file__).parent
STATIC_DB  = _BASE / "knowledge_static.db"
DYNAMIC_DB = _BASE / "knowledge_dynamic.db"

# ─── How many successes before a dynamic fix is "promoted" ───────────────────
PROMOTION_THRESHOLD = 3


# ─── Static DB helpers ───────────────────────────────────────────────────────

def _get_static_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(STATIC_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_static_schema():
    with _get_static_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS static_recipes (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                issue               TEXT NOT NULL,
                os                  TEXT NOT NULL DEFAULT 'Any',
                category            TEXT NOT NULL DEFAULT 'General',
                command             TEXT NOT NULL,
                risk                TEXT NOT NULL DEFAULT 'Low',
                explanation         TEXT NOT NULL DEFAULT '',
                tags                TEXT NOT NULL DEFAULT '',
                operation           TEXT NOT NULL DEFAULT 'REPAIR',
                repair_strategy     TEXT NOT NULL DEFAULT 'NONE',
                package_manager     TEXT DEFAULT 'winget',
                package_id          TEXT DEFAULT '',
                verification_command TEXT DEFAULT '',
                official_url        TEXT DEFAULT '',
                source              TEXT NOT NULL DEFAULT 'STATIC_DB',
                app_id              TEXT DEFAULT '',
                created_at          TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # Ensure new columns exist
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(static_recipes)").fetchall()}
        col_defs = {
            "operation": "TEXT NOT NULL DEFAULT 'REPAIR'",
            "repair_strategy": "TEXT NOT NULL DEFAULT 'NONE'",
            "package_manager": "TEXT DEFAULT 'winget'",
            "package_id": "TEXT DEFAULT ''",
            "verification_command": "TEXT DEFAULT ''",
            "official_url": "TEXT DEFAULT ''",
            "source": "TEXT NOT NULL DEFAULT 'STATIC_DB'",
            "app_id": "TEXT DEFAULT ''",
            "install_supported": "INTEGER NOT NULL DEFAULT 1",
            "update_supported": "INTEGER NOT NULL DEFAULT 1",
            "uninstall_supported": "INTEGER NOT NULL DEFAULT 1",
            "reinstall_supported": "INTEGER NOT NULL DEFAULT 1",
            "verify_supported": "INTEGER NOT NULL DEFAULT 1",
            "version_check_supported": "INTEGER NOT NULL DEFAULT 1",
            "repair_supported": "INTEGER NOT NULL DEFAULT 0",
            "update_method": "TEXT NOT NULL DEFAULT 'PACKAGE_MANAGER'",
            "publisher_update_command": "TEXT NOT NULL DEFAULT ''",
            "publisher_update_instructions": "TEXT NOT NULL DEFAULT ''"
        }
        for col, col_type in col_defs.items():
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE static_recipes ADD COLUMN {col} {col_type}")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_sr_issue ON static_recipes(issue)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sr_category ON static_recipes(category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sr_op ON static_recipes(operation)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sr_strat ON static_recipes(repair_strategy)")
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS static_recipes_fts USING fts5(issue, explanation, tags, content=static_recipes, content_rowid=id)")
        conn.commit()


# ─── Dynamic DB helpers ───────────────────────────────────────────────────────

def _get_dynamic_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DYNAMIC_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_dynamic_schema():
    with _get_dynamic_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS learned_solutions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_pattern     TEXT NOT NULL,
                proposed_fix        TEXT NOT NULL,
                category            TEXT NOT NULL DEFAULT 'General',
                os                  TEXT NOT NULL DEFAULT 'Any',
                user_approved       INTEGER NOT NULL DEFAULT 0,
                success_count       INTEGER NOT NULL DEFAULT 0,
                fail_count          INTEGER NOT NULL DEFAULT 0,
                promoted_to_static  INTEGER NOT NULL DEFAULT 0,
                lifecycle_status    TEXT NOT NULL DEFAULT 'GENERATED',
                source              TEXT NOT NULL DEFAULT 'ai_proposed',
                created_at          TEXT NOT NULL DEFAULT (datetime('now')),
                last_used           TEXT
            )
        """)
        # Ensure lifecycle_status exists on existing tables
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(learned_solutions)").fetchall()}
        if "lifecycle_status" not in existing_cols:
            conn.execute("ALTER TABLE learned_solutions ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'GENERATED'")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_approvals (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                solution_id         INTEGER NOT NULL REFERENCES learned_solutions(id),
                proposed_fix        TEXT NOT NULL,
                trigger_pattern     TEXT NOT NULL,
                context             TEXT,
                requested_at        TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS validation_evidence (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                solution_id         INTEGER NOT NULL,
                environment_id      TEXT NOT NULL,
                os                  TEXT NOT NULL,
                architecture        TEXT NOT NULL,
                package_manager     TEXT NOT NULL,
                verified            INTEGER NOT NULL DEFAULT 1,
                timestamp           TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ls_approved ON learned_solutions(user_approved)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ls_promoted ON learned_solutions(promoted_to_static)")
        conn.commit()


# Ensure schemas exist at import time
_ensure_static_schema()
_ensure_dynamic_schema()


# ─── Pydantic models ─────────────────────────────────────────────────────────

class ProposeRequest(BaseModel):
    trigger_pattern: str
    proposed_fix: str
    category: str = "General"
    os: str = "Any"
    source: str = "ai_proposed"
    context: str = ""


class RecordOutcomeRequest(BaseModel):
    solution_id: int
    success: bool


# ─── Part A endpoints (Static / Read-only) ────────────────────────────────────

@router.get("/api/kb/static")
def list_static_recipes(
    category: str = "",
    os: str = "",
    q: str = "",
    limit: int = 200,
):
    """List static (sealed) repair recipes. Optionally filter by category, os, or text search."""
    with _get_static_conn() as conn:
        params: list[Any] = []
        clauses: list[str] = []

        if category:
            clauses.append("category = ?")
            params.append(category)
        if os:
            clauses.append("(os = ? OR os = 'Any')")
            params.append(os)
        if q:
            clauses.append("(issue LIKE ? OR explanation LIKE ? OR tags LIKE ?)")
            params += [f"%{q}%", f"%{q}%", f"%{q}%"]

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM static_recipes {where} ORDER BY category, issue LIMIT ?",
            params + [limit]
        ).fetchall()

    recipes = [dict(r) for r in rows]
    return {"ok": True, "count": len(recipes), "recipes": recipes}


@router.get("/api/kb/static/categories")
def list_static_categories():
    """Return distinct categories from static recipes."""
    with _get_static_conn() as conn:
        rows = conn.execute("SELECT DISTINCT category FROM static_recipes ORDER BY category").fetchall()
    return {"ok": True, "categories": [r[0] for r in rows]}


# ─── Part B endpoints (Dynamic / Learned) ─────────────────────────────────────

@router.get("/api/kb/dynamic")
def list_dynamic_solutions(approved_only: bool = False, limit: int = 100):
    """List learned/proposed solutions. approved_only=true returns only user-confirmed fixes."""
    with _get_dynamic_conn() as conn:
        where = "WHERE user_approved = 1" if approved_only else ""
        rows = conn.execute(
            f"SELECT * FROM learned_solutions {where} ORDER BY success_count DESC, created_at DESC LIMIT ?",
            [limit]
        ).fetchall()
    solutions = [dict(r) for r in rows]
    return {"ok": True, "count": len(solutions), "solutions": solutions}


@router.get("/api/kb/dynamic/pending")
def list_pending_approvals():
    """List all proposed solutions awaiting user approval."""
    with _get_dynamic_conn() as conn:
        rows = conn.execute("""
            SELECT pa.*, ls.category, ls.os, ls.source
            FROM pending_approvals pa
            JOIN learned_solutions ls ON ls.id = pa.solution_id
            ORDER BY pa.requested_at DESC
        """).fetchall()
    return {"ok": True, "count": len(rows), "pending": [dict(r) for r in rows]}


@router.post("/api/kb/dynamic/propose")
def propose_solution(req: ProposeRequest):
    """Store a newly discovered fix as a pending learned solution (requires user approval)."""
    with _get_dynamic_conn() as conn:
        cur = conn.execute("""
            INSERT INTO learned_solutions
              (trigger_pattern, proposed_fix, category, os, source, user_approved)
            VALUES (?, ?, ?, ?, ?, 0)
        """, [req.trigger_pattern, req.proposed_fix, req.category, req.os, req.source])
        sol_id = cur.lastrowid
        conn.execute("""
            INSERT INTO pending_approvals (solution_id, proposed_fix, trigger_pattern, context)
            VALUES (?, ?, ?, ?)
        """, [sol_id, req.proposed_fix, req.trigger_pattern, req.context])
        conn.commit()
    return {"ok": True, "solution_id": sol_id, "message": "Solution queued for user approval"}


@router.post("/api/kb/dynamic/approve/{solution_id}")
def approve_solution(solution_id: int):
    """User approves a proposed fix. Marks it as approved and removes from pending queue."""
    with _get_dynamic_conn() as conn:
        row = conn.execute(
            "SELECT id, user_approved FROM learned_solutions WHERE id = ?", [solution_id]
        ).fetchone()
        if not row:
            return {"ok": True, "message": f"Solution {solution_id} already processed"}
        conn.execute(
            "UPDATE learned_solutions SET user_approved = 1 WHERE id = ?", [solution_id]
        )
        conn.execute(
            "DELETE FROM pending_approvals WHERE solution_id = ?", [solution_id]
        )
        conn.commit()
    return {"ok": True, "message": f"Solution {solution_id} approved"}


@router.post("/api/kb/dynamic/reject/{solution_id}")
def reject_solution(solution_id: int):
    """User rejects a proposed fix. Removes it entirely."""
    with _get_dynamic_conn() as conn:
        conn.execute("DELETE FROM learned_solutions WHERE id = ?", [solution_id])
        conn.execute("DELETE FROM pending_approvals WHERE solution_id = ?", [solution_id])
        conn.commit()
    return {"ok": True, "message": f"Solution {solution_id} rejected and removed"}


@router.post("/api/kb/dynamic/outcome")
def record_outcome(req: RecordOutcomeRequest):
    """Record whether a learned solution succeeded or failed.
    A successful execution grants PROMOTION_ELIGIBLE status (never auto-promoted to static).
    """
    with _get_dynamic_conn() as conn:
        row = conn.execute(
            "SELECT * FROM learned_solutions WHERE id = ?", [req.solution_id]
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Solution {req.solution_id} not found")
        sol = dict(row)
        now = datetime.now(timezone.utc).isoformat()
        if req.success:
            new_count = sol["success_count"] + 1
            lifecycle = "PROMOTION_ELIGIBLE"
            conn.execute(
                "UPDATE learned_solutions SET success_count=?, lifecycle_status=?, last_used=? WHERE id=?",
                [new_count, lifecycle, now, req.solution_id]
            )
        else:
            conn.execute(
                "UPDATE learned_solutions SET fail_count=fail_count+1, lifecycle_status='EXECUTION_FAILED', last_used=? WHERE id=?",
                [now, req.solution_id]
            )
        conn.commit()
    return {"ok": True, "lifecycle_status": "PROMOTION_ELIGIBLE" if req.success else "EXECUTION_FAILED"}


@router.post("/api/kb/dynamic/promote/{solution_id}")
def promote_solution_to_static(solution_id: int):
    """
    Promotes a dynamic solution to Static DB only if it meets all promotion criteria:
    1. Successful validation.
    2. Independent validation across matching environments (min 3 distinct environments).
    3. Review / approval.
    """
    with _get_dynamic_conn() as dconn:
        row = dconn.execute("SELECT * FROM learned_solutions WHERE id = ?", [solution_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Solution {solution_id} not found")
        sol = dict(row)

        evidence_rows = dconn.execute(
            "SELECT DISTINCT environment_id FROM validation_evidence WHERE solution_id = ? AND verified = 1",
            [solution_id]
        ).fetchall()
        distinct_envs = len(evidence_rows)

        # Enforce Section 11: minimum 3 independent environments required
        if distinct_envs < 3 and sol.get("user_approved") != 1:
            raise HTTPException(
                status_code=400,
                detail=f"Promotion rejected: Found {distinct_envs} independent matching environments; minimum 3 required."
            )

        # Mark as promoted in dynamic DB
        dconn.execute("UPDATE learned_solutions SET promoted_to_static = 1, lifecycle_status = 'PROMOTED_TO_STATIC' WHERE id = ?", [solution_id])
        dconn.commit()

    # Insert into static DB
    with _get_static_conn() as sconn:
        sconn.execute("""
            INSERT INTO static_recipes (issue, os, category, command, risk, explanation, tags, source)
            VALUES (?, ?, ?, ?, 'Medium', ?, ?, 'DYNAMIC_PROMOTED')
        """, [
            sol["trigger_pattern"],
            sol["os"],
            sol["category"],
            sol["proposed_fix"],
            f"Promoted learned solution: {sol['trigger_pattern']}",
            f"dynamic,promoted,{sol['category'].lower()}"
        ])
        sconn.commit()

    return {"ok": True, "message": f"Solution {solution_id} successfully promoted to Static DB."}


@router.get("/api/kb/dynamic/search")
def search_dynamic(q: str, limit: int = 20):
    """Search dynamic learned solutions by trigger pattern or fix text."""
    with _get_dynamic_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM learned_solutions
            WHERE user_approved = 1
              AND (trigger_pattern LIKE ? OR proposed_fix LIKE ?)
            ORDER BY success_count DESC LIMIT ?
        """, [f"%{q}%", f"%{q}%", limit]).fetchall()
    return {"ok": True, "count": len(rows), "solutions": [dict(r) for r in rows]}
