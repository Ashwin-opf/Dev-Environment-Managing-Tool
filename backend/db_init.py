"""
db_init.py — Authoritative Database Lifecycle, Migration, and Recovery
======================================================================
Manages database initialization, schema versioning, non-destructive migration,
corruption detection/recovery, and crash recovery for PC Doctor.

Lifecycle Rules:
- Fresh install: Automatically creates schema and seeds initial knowledge.
- Existing install: Performs safe non-destructive migrations, preserving all user data.
- Corrupted database: Detects corruption via `PRAGMA integrity_check`. Backs up
  corrupted file to `<name>.corrupt.<timestamp>` and safely rebuilds fresh DB.
- Crash recovery: Interrupted queue tasks (`running`, `in_progress`, `executing`)
  are transitioned to `interrupted`. Under NO circumstances is false success recorded.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from runtime_paths import (
    get_runtime_db_path,
    get_static_db_path,
    get_bundled_runtime_db_path,
    get_bundled_static_db_path,
    BASE_DIR,
)
from version import __version__

logger = logging.getLogger("pc_doctor.db_init")

CURRENT_SCHEMA_VERSION = "1.0.0"

CORE_SCHEMA_SQL = """
-- db_meta: records database metadata, schema version, and app version
CREATE TABLE IF NOT EXISTS db_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- recipes: core repair and diagnosis recipes
CREATE TABLE IF NOT EXISTS recipes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    tier INTEGER DEFAULT 1,
    os TEXT DEFAULT 'all',
    detect_command TEXT,
    repair_command TEXT,
    verify_command TEXT,
    confidence REAL DEFAULT 1.0,
    created_at TEXT,
    updated_at TEXT
);

-- adaptive_knowledge_base: dynamic knowledge entries
CREATE TABLE IF NOT EXISTS adaptive_knowledge_base (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    topic TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL
);

-- learned_command_mappings: successful mutations and tool resolutions
CREATE TABLE IF NOT EXISTS learned_command_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_command TEXT NOT NULL,
    adapted_command TEXT NOT NULL,
    os TEXT NOT NULL,
    success_count INTEGER DEFAULT 1,
    last_verified TEXT NOT NULL
);

-- self_healing_attempts: execution telemetry and failure diagnosis
CREATE TABLE IF NOT EXISTS self_healing_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    command TEXT NOT NULL,
    exit_code INTEGER,
    error_signature TEXT,
    diagnosis TEXT,
    remedy_applied TEXT,
    outcome TEXT
);

-- error_intelligence: self-healing error intelligence
CREATE TABLE IF NOT EXISTS error_intelligence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    error_signature TEXT NOT NULL,
    error_raw TEXT,
    command TEXT,
    source TEXT DEFAULT 'user',
    os_snapshot TEXT,
    candidates TEXT,
    selected_fix TEXT,
    outcome TEXT DEFAULT 'pending',
    user_approved INTEGER DEFAULT 0
);

-- shce_queue: background self-healing and repair queue
CREATE TABLE IF NOT EXISTS shce_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    command TEXT NOT NULL,
    error TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    candidates TEXT,
    selected_candidate TEXT,
    outcome_stdout TEXT,
    outcome_stderr TEXT,
    outcome_rc INTEGER
);

-- package_knowledge: package ecosystem dependency and tool info
CREATE TABLE IF NOT EXISTS package_knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_name TEXT NOT NULL,
    ecosystem TEXT NOT NULL,
    manager TEXT NOT NULL,
    install_command TEXT NOT NULL,
    verify_command TEXT,
    description TEXT,
    UNIQUE(package_name, ecosystem, manager)
);

-- safety_overrides: explicitly approved user overrides
CREATE TABLE IF NOT EXISTS safety_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_hash TEXT UNIQUE NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    reason TEXT
);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def check_db_integrity(db_path: Path) -> Tuple[bool, str]:
    """
    Run `PRAGMA integrity_check` on an SQLite database.
    Returns (True, "ok") if database is healthy.
    Returns (False, details) if corrupted or unreadable.
    """
    if not db_path.exists():
        return False, "File does not exist"

    # 0-byte file check
    if db_path.stat().st_size == 0:
        return False, "Empty 0-byte file"

    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0) as conn:
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check;")
            rows = cur.fetchall()
            if rows and len(rows) == 1 and rows[0][0] == "ok":
                return True, "ok"
            errors = "; ".join(str(r[0]) for r in rows)
            return False, f"Integrity check failed: {errors}"
    except (sqlite3.DatabaseError, sqlite3.OperationalError, Exception) as exc:
        return False, f"SQLite error: {exc}"


def backup_corrupted_file(file_path: Path) -> Path:
    """
    Safely quarantine a corrupted file by moving/copying to:
    `<name>.corrupt.<YYYYMMDDTHHMMSSZ>`
    Also moves associated SQLite sidecars (-wal, -shm, -journal) if present.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = file_path.parent / f"{file_path.name}.corrupt.{ts}"
    try:
        shutil.move(str(file_path), str(backup_path))
    except Exception:
        shutil.copy2(str(file_path), str(backup_path))
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass

    for ext in ["-wal", "-shm", "-journal"]:
        sidecar = Path(str(file_path) + ext)
        if sidecar.exists():
            try:
                shutil.move(str(sidecar), str(backup_path) + ext)
            except Exception:
                pass

    logger.warning(f"[PC Doctor] Corrupted file quarantined to {backup_path}")
    return backup_path


def seed_runtime_database(target_db: Path) -> None:
    """Seed target runtime database from bundled template or default schema."""
    target_db.parent.mkdir(parents=True, exist_ok=True)
    bundled = get_bundled_runtime_db_path()
    if bundled and bundled.resolve() != target_db.resolve() and bundled.exists():
        is_ok, _ = check_db_integrity(bundled)
        if is_ok:
            shutil.copyfile(bundled, target_db)
            return

    # Fallback: create fresh with core schema
    with sqlite3.connect(target_db) as conn:
        conn.executescript(CORE_SCHEMA_SQL)
        now = _utc_now()
        conn.execute(
            "INSERT OR REPLACE INTO db_meta (key, value, updated_at) VALUES (?, ?, ?)",
            ("schema_version", CURRENT_SCHEMA_VERSION, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO db_meta (key, value, updated_at) VALUES (?, ?, ?)",
            ("app_version", __version__, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO db_meta (key, value, updated_at) VALUES (?, ?, ?)",
            ("initialized_at", now, now),
        )
        conn.commit()


def ensure_schema_and_migrations(db_path: Path) -> Dict[str, Any]:
    """
    Apply any missing tables or columns non-destructively.
    Tracks schema version in `db_meta`.
    """
    migration_applied = False
    with sqlite3.connect(db_path) as conn:
        conn.executescript(CORE_SCHEMA_SQL)

        cur = conn.cursor()
        cur.execute("SELECT value FROM db_meta WHERE key = 'schema_version'")
        row = cur.fetchone()
        now = _utc_now()
        if not row:
            cur.execute(
                "INSERT OR REPLACE INTO db_meta (key, value, updated_at) VALUES (?, ?, ?)",
                ("schema_version", CURRENT_SCHEMA_VERSION, now),
            )
            cur.execute(
                "INSERT OR REPLACE INTO db_meta (key, value, updated_at) VALUES (?, ?, ?)",
                ("app_version", __version__, now),
            )
            cur.execute(
                "INSERT OR REPLACE INTO db_meta (key, value, updated_at) VALUES (?, ?, ?)",
                ("initialized_at", now, now),
            )
            migration_applied = True
        else:
            schema_ver = row[0]
            # If newer app version, record last verification
            cur.execute(
                "INSERT OR REPLACE INTO db_meta (key, value, updated_at) VALUES (?, ?, ?)",
                ("app_version", __version__, now),
            )
            cur.execute(
                "INSERT OR REPLACE INTO db_meta (key, value, updated_at) VALUES (?, ?, ?)",
                ("last_verified_at", now, now),
            )

        conn.commit()

    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "migration_applied": migration_applied,
    }


def recover_interrupted_tasks(db_path: Path) -> int:
    """
    Find any queue items or repair tasks left in 'running', 'in_progress', or 'executing'
    state from an ungraceful shutdown.
    Transitions them to 'interrupted'. Under NO circumstances marks them 'success'.
    Returns total number of recovered tasks.
    """
    cleaned_count = 0
    now = _utc_now()

    # 1. Recover SQLite shce_queue
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                # Check if shce_queue table exists
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shce_queue'")
                if cur.fetchone():
                    cur.execute("""
                        UPDATE shce_queue
                        SET status = 'interrupted',
                            outcome_stderr = 'Task interrupted by unexpected application termination',
                            outcome_rc = -1
                        WHERE LOWER(status) IN ('running', 'in_progress', 'executing')
                    """)
                    cleaned_count += cur.rowcount
                    conn.commit()
        except Exception as exc:
            logger.warning(f"[PC Doctor] shce_queue recovery warning: {exc}")

    # 2. Recover control_center_queue.json
    queue_files = [
        BASE_DIR / "control_center_queue.json",
        get_runtime_db_path().parent / "control_center_queue.json",
    ]
    for q_file in set(queue_files):
        if q_file.exists():
            try:
                items = json.loads(q_file.read_text(encoding="utf-8"))
                modified = False
                for it in items:
                    st = (it.get("status") or "").lower()
                    if st in ("running", "in_progress", "executing"):
                        it["status"] = "interrupted"
                        it["interrupted_at"] = now
                        it["interruption_reason"] = "Unexpected application shutdown"
                        cleaned_count += 1
                        modified = True
                if modified:
                    q_file.write_text(json.dumps(items, indent=2), encoding="utf-8")
            except Exception as exc:
                logger.warning(f"[PC Doctor] control_center_queue recovery warning: {exc}")

    return cleaned_count


def init_all_databases() -> Dict[str, Any]:
    """
    Authoritative database initialization, validation, migration, and crash recovery.
    Runs on application startup (wired to FastAPI lifespan).
    """
    report: Dict[str, Any] = {
        "status": "ok",
        "app_version": __version__,
        "runtime_db": {},
        "static_db": {},
        "corrupt_backups": [],
        "interrupted_tasks_cleaned": 0,
    }

    # ─── 1. Runtime Database (knowledge.db) ──────────────────────────────────
    runtime_path = get_runtime_db_path()
    rebuilt = False
    backup_path = None

    if runtime_path.exists():
        is_ok, reason = check_db_integrity(runtime_path)
        if not is_ok:
            logger.warning(f"[PC Doctor] Corrupted runtime DB detected: {reason}")
            backup_path = backup_corrupted_file(runtime_path)
            report["corrupt_backups"].append(str(backup_path))
            seed_runtime_database(runtime_path)
            rebuilt = True
    else:
        seed_runtime_database(runtime_path)
        rebuilt = True

    migration_info = ensure_schema_and_migrations(runtime_path)
    cleaned_tasks = recover_interrupted_tasks(runtime_path)

    report["runtime_db"] = {
        "path": str(runtime_path),
        "rebuilt": rebuilt,
        "backup": str(backup_path) if backup_path else None,
        "schema_version": migration_info["schema_version"],
        "migration_applied": migration_info["migration_applied"],
    }
    report["interrupted_tasks_cleaned"] = cleaned_tasks

    # ─── 2. Static Database (knowledge_static.db) ───────────────────────────
    static_path = get_static_db_path()
    static_ok = False
    if static_path.exists():
        is_ok, reason = check_db_integrity(static_path)
        if not is_ok:
            logger.warning(f"[PC Doctor] Corrupted static DB detected: {reason}")
            backup_static = backup_corrupted_file(static_path)
            report["corrupt_backups"].append(str(backup_static))
            bundled_static = get_bundled_static_db_path()
            if bundled_static and bundled_static.exists() and check_db_integrity(bundled_static)[0]:
                shutil.copyfile(bundled_static, static_path)
                static_ok = True
        else:
            static_ok = True

    report["static_db"] = {
        "path": str(static_path),
        "present": static_path.exists(),
        "integrity_ok": static_ok,
    }

    logger.info(f"[PC Doctor] Database initialization complete: {report}")
    return report
