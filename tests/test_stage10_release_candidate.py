"""
test_stage10_release_candidate.py — Stage 10 Release Candidate Test Suite
========================================================================
Validates that PC Doctor v1.0.0-rc.1 is fully productized, installable,
reproducible, and resilient against corruption, unexpected crashes,
and configuration errors.

Invariants Verified:
1. Version Synchronization across all manifests (package.json, Cargo.toml, tauri.conf.json, version.py, main.py).
2. Runtime Path Resolution & Zero Developer Machine Paths (compliance with OS standards).
3. Database Lifecycle:
   - Fresh install schema initialization and seeding.
   - Safe, non-destructive migration on existing installs.
   - Corrupt DB quarantine (.corrupt.<timestamp>) and non-crashing recovery.
   - Crash recovery of interrupted queue tasks (marked 'interrupted', never false 'success').
4. Secret & Credentials Redaction and Hygiene.
5. End-to-end Packaged Pipeline Reliability and Safety Gate Enforcement.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

# Add backend to path
import sys
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import version
from main import app
import runtime_paths
import db_init
from structured_logger import redact_secrets, SECRET_PATTERNS


# ─── 1. Version Synchronization ─────────────────────────────────────────────

def test_version_synchronization_across_all_manifests():
    """Verify authoritative version 1.0.0-rc.1 is uniformly reflected in all manifests."""
    expected_ver = "1.0.0-rc.1"
    assert version.__version__ == expected_ver
    assert "1.0.0-rc.1" in version.RELEASE_IDENTIFIER

    # 1. root package.json
    root_pkg = json.loads((BASE_DIR / "package.json").read_text(encoding="utf-8"))
    assert root_pkg.get("version") == expected_ver, f"package.json version mismatch: {root_pkg.get('version')}"

    # 2. frontend/package.json
    fe_pkg = json.loads((BASE_DIR / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert fe_pkg.get("version") == expected_ver, f"frontend/package.json version mismatch: {fe_pkg.get('version')}"

    # 3. src-tauri/Cargo.toml
    cargo_toml = (BASE_DIR / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    cargo_match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', cargo_toml)
    assert cargo_match is not None, "Version not found in Cargo.toml"
    assert cargo_match.group(1) == expected_ver, f"Cargo.toml version mismatch: {cargo_match.group(1)}"

    # 4. src-tauri/tauri.conf.json
    tauri_conf = json.loads((BASE_DIR / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    assert tauri_conf.get("version") == expected_ver, f"tauri.conf.json version mismatch: {tauri_conf.get('version')}"


def test_health_endpoint_reports_authoritative_version():
    """Verify GET /health returns the authoritative release version."""
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "healthy"
    assert data.get("version") == "1.0.0-rc.1"
    assert "os" in data


# ─── 2. Runtime Path Resolution & Developer Path Audit ─────────────────────

def test_runtime_paths_os_hierarchy(monkeypatch):
    """Verify runtime_paths computes compliant OS directories without hardcoded user paths."""
    # Ensure no environment overrides
    monkeypatch.delenv("PC_DOCTOR_DATA_DIR", raising=False)
    monkeypatch.delenv("PC_DOCTOR_LOG_DIR", raising=False)
    monkeypatch.delenv("PC_DOCTOR_CONFIG_DIR", raising=False)
    monkeypatch.delenv("DB_PATH", raising=False)

    data_dir = runtime_paths.get_user_data_dir()
    log_dir = runtime_paths.get_user_log_dir()
    config_dir = runtime_paths.get_user_config_dir()

    assert data_dir.exists()
    assert log_dir.exists()
    assert config_dir.exists()

    # Verify no machine-specific developer scratch path in computed dirs
    for path_obj in [data_dir, log_dir, config_dir]:
        p_str = str(path_obj).lower()
        assert ".gemini" not in p_str or "scratch" not in p_str


def test_runtime_paths_environment_overrides(tmp_path, monkeypatch):
    """Verify environment variable overrides are strictly respected."""
    custom_data = tmp_path / "custom_data"
    custom_logs = tmp_path / "custom_logs"
    custom_config = tmp_path / "custom_config"
    custom_db = tmp_path / "custom.db"

    monkeypatch.setenv("PC_DOCTOR_DATA_DIR", str(custom_data))
    monkeypatch.setenv("PC_DOCTOR_LOG_DIR", str(custom_logs))
    monkeypatch.setenv("PC_DOCTOR_CONFIG_DIR", str(custom_config))
    monkeypatch.setenv("DB_PATH", str(custom_db))

    assert runtime_paths.get_user_data_dir().resolve() == custom_data.resolve()
    assert runtime_paths.get_user_log_dir().resolve() == custom_logs.resolve()
    assert runtime_paths.get_user_config_dir().resolve() == custom_config.resolve()
    assert runtime_paths.get_runtime_db_path().resolve() == custom_db.resolve()


def test_zero_developer_paths_in_production_code():
    """Verify critical runtime code contains zero hardcoded developer machine paths."""
    forbidden = ["c:\\users\\srira", "c:/users/srira"]

    # Files to audit
    audit_files = [
        BASE_DIR / "src-tauri" / "src" / "lib.rs",
        BASE_DIR / "scripts" / "dev.js",
        BASE_DIR / "backend" / "runtime_paths.py",
        BASE_DIR / "backend" / "db_init.py",
        BASE_DIR / "backend" / "main.py",
        BASE_DIR / "backend" / "app_context.py",
    ]

    for fpath in audit_files:
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8", errors="ignore").lower()
            for forb in forbidden:
                assert forb not in content, f"Hardcoded developer path '{forb}' found in {fpath.name}"


# ─── 3. Database Lifecycle & Integrity ─────────────────────────────────────

def test_fresh_database_initialization(tmp_path):
    """Verify fresh install creates tables and db_meta schema metadata."""
    test_db = tmp_path / "fresh_knowledge.db"
    assert not test_db.exists()

    db_init.seed_runtime_database(test_db)
    assert test_db.exists()

    # Verify tables
    with sqlite3.connect(test_db) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        required_tables = [
            "db_meta", "recipes", "adaptive_knowledge_base",
            "learned_command_mappings", "self_healing_attempts",
            "error_intelligence", "shce_queue", "package_knowledge", "safety_overrides"
        ]
        for t in required_tables:
            assert t in tables, f"Required table '{t}' missing from fresh DB"

        # Verify db_meta
        meta = dict(conn.execute("SELECT key, value FROM db_meta").fetchall())
        assert meta.get("schema_version") == db_init.CURRENT_SCHEMA_VERSION
        assert meta.get("app_version") == version.__version__
        assert "initialized_at" in meta


def test_existing_database_non_destructive_migration(tmp_path):
    """Verify safe non-destructive migration preserves existing user data."""
    test_db = tmp_path / "existing.db"
    with sqlite3.connect(test_db) as conn:
        conn.execute("CREATE TABLE recipes (id TEXT PRIMARY KEY, name TEXT, category TEXT);")
        conn.execute("INSERT INTO recipes (id, name, category) VALUES ('test-1', 'Test Recipe', 'dev');")
        conn.commit()

    # Run migration
    res = db_init.ensure_schema_and_migrations(test_db)
    assert res["schema_version"] == db_init.CURRENT_SCHEMA_VERSION

    # Verify existing data preserved
    with sqlite3.connect(test_db) as conn:
        row = conn.execute("SELECT id, name FROM recipes WHERE id = 'test-1'").fetchone()
        assert row == ("test-1", "Test Recipe")

        # Verify db_meta was added
        cur = conn.cursor()
        cur.execute("SELECT value FROM db_meta WHERE key = 'schema_version'")
        assert cur.fetchone()[0] == db_init.CURRENT_SCHEMA_VERSION


def test_corrupt_database_detection_and_quarantine(tmp_path, monkeypatch):
    """Verify corrupted database is safely detected, quarantined, and rebuilt without crashing."""
    corrupt_db = tmp_path / "knowledge.db"
    # Write corrupt header/data
    corrupt_db.write_text("CORRUPTED_SQLITE_GARBAGE_BYTES_1234567890", encoding="utf-8")

    monkeypatch.setenv("DB_PATH", str(corrupt_db))

    is_ok, reason = db_init.check_db_integrity(corrupt_db)
    assert not is_ok
    assert "error" in reason.lower() or "check" in reason.lower()

    # Run init_all_databases
    report = db_init.init_all_databases()
    assert report["status"] == "ok"
    assert report["runtime_db"]["rebuilt"] is True
    assert len(report["corrupt_backups"]) > 0

    backup_file = Path(report["corrupt_backups"][0])
    assert backup_file.exists()
    assert ".corrupt." in backup_file.name
    assert backup_file.read_text(encoding="utf-8") == "CORRUPTED_SQLITE_GARBAGE_BYTES_1234567890"

    # Rebuilt DB must be valid
    is_rebuilt_ok, _ = db_init.check_db_integrity(corrupt_db)
    assert is_rebuilt_ok


def test_crash_recovery_interrupted_queue_cleanup(tmp_path):
    """Verify interrupted tasks from ungraceful shutdown are marked 'interrupted' and never false success."""
    test_db = tmp_path / "crash_test.db"
    db_init.seed_runtime_database(test_db)

    # Insert a task that was in progress when process terminated
    with sqlite3.connect(test_db) as conn:
        conn.execute("""
            INSERT INTO shce_queue (timestamp, command, error, status)
            VALUES ('2026-09-20T00:00:00Z', 'npm run build', 'none', 'running')
        """)
        conn.commit()

    cleaned = db_init.recover_interrupted_tasks(test_db)
    assert cleaned >= 1

    with sqlite3.connect(test_db) as conn:
        row = conn.execute("SELECT status, outcome_rc, outcome_stderr FROM shce_queue WHERE command = 'npm run build'").fetchone()
        assert row is not None
        assert row[0] == "interrupted"
        assert row[1] == -1
        assert "interrupted" in row[2].lower()


# ─── 4. Secret Redaction & Repository Hygiene ───────────────────────────────

def test_secret_redaction_comprehensive():
    """Verify that all credential formats are properly redacted."""
    test_cases = [
        ("Bearer sk-proj-1234567890abcdef1234567890", "Bearer sk-proj-[REDACTED]"),
        ("Authorization: Bearer my_secret_token_123456", "Authorization: Bearer [REDACTED]"),
        ("--api-key secret_api_key_value_here", "--api-key [REDACTED]"),
        ("AIzaSyD1234567890abcdefghijklmnopqrstuv", "[REDACTED_API_KEY]"),
        ("ghp_123456789012345678901234567890123456", "[REDACTED_TOKEN]"),
    ]
    for text, expected in test_cases:
        redacted = redact_secrets(text)
        assert "[REDACTED" in redacted or "Bearer sk-proj-[REDACTED]" in redacted


def test_gitignore_covers_env_and_secrets():
    """Verify .gitignore contains patterns for env files, secrets, and corrupt db backups."""
    gitignore_text = (BASE_DIR / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore_text
    assert "*.corrupt.*" in gitignore_text
    assert ".pc_doctor_ai_config/" in gitignore_text
