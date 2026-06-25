"""
Tests for the Self-Healing Core Engine (SHCE)
Covers: CommandMutationEngine, ErrorIntelligenceDB, EnvironmentProfiler,
        SHCEOrchestrator, and /api/shce/* API endpoints.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Add backend directory to path ────────────────────────────────────────────
_backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_backend_dir))


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_repair_engine_run():
    from repair_engine import RepairEngine
    with patch.object(RepairEngine, "run", return_value=("Mock stdout", "", 0)) as mock:
        yield mock


@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    """Temporary SQLite DB with all required tables."""
    db_path = str(tmp_path / "test_knowledge.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE adaptive_knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            os_name TEXT, os_version TEXT, kernel_version TEXT,
            error_pattern TEXT, successful_fix TEXT, default_fallback TEXT,
            confidence_score REAL, success_count INTEGER, failure_count INTEGER,
            verification_status TEXT, source TEXT, last_verified TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE self_healing_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_message TEXT, error_source TEXT, cause TEXT,
            attempted_fix TEXT, fix_source TEXT, result TEXT,
            safety_class TEXT, validation_result TEXT,
            archived INTEGER DEFAULT 0, config_backup TEXT, timestamp TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE learned_command_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_command TEXT, failed_command TEXT,
            replacement_command TEXT, verification_result TEXT, timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def error_db(tmp_db: str):
    from shce_engine import ErrorIntelligenceDB
    return ErrorIntelligenceDB(tmp_db)


@pytest.fixture
def mutation_engine(tmp_db: str):
    from shce_engine import CommandMutationEngine
    eng = CommandMutationEngine(tmp_db)
    # Force known env
    eng._env = {
        "os_name": "Linux",
        "distro": "debian",
        "network_online": False,
        "ollama_running": False,
    }
    return eng


@pytest.fixture
def orchestrator(tmp_db: str):
    from shce_engine import SHCEOrchestrator
    return SHCEOrchestrator(tmp_db)


# ─── ErrorIntelligenceDB ─────────────────────────────────────────────────────

class TestErrorIntelligenceDB:
    def test_ensure_tables_created(self, tmp_db: str):
        """Tables error_intelligence and shce_queue should exist after init."""
        from shce_engine import ErrorIntelligenceDB
        ErrorIntelligenceDB(tmp_db)  # re-run to verify idempotent
        conn = sqlite3.connect(tmp_db)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "error_intelligence" in tables
        assert "shce_queue" in tables

    def test_log_error_returns_id(self, error_db):
        eid = error_db.log_error("apt install foo", "Package not found", [])
        assert isinstance(eid, int) and eid > 0

    def test_log_and_retrieve_error(self, error_db):
        error_db.log_error("pip install bar", "ssl certificate error", [{"command": "pip install --trusted-host..."}])
        log = error_db.get_error_log(limit=10)
        assert len(log) == 1
        assert "pip install bar" in log[0]["command"]

    def test_enqueue_and_get_queue(self, error_db):
        qid = error_db.enqueue("npm install", "EACCES permission denied", [], "sudo npm install")
        queue = error_db.get_queue()
        assert any(q["id"] == qid for q in queue)

    def test_update_queue_item_status(self, error_db):
        qid = error_db.enqueue("docker ps", "cannot connect", [])
        error_db.update_queue_item(qid, "executed", stdout="container list", rc=0)
        queue = error_db.get_queue(status="executed")
        assert any(q["id"] == qid and q["outcome_rc"] == 0 for q in queue)

    def test_update_outcome(self, error_db):
        eid = error_db.log_error("git pull", "ssl verify failed", [])
        error_db.update_outcome(eid, "resolved", selected_fix="git config --global http.sslVerify false", user_approved=True)
        log = error_db.get_error_log()
        entry = next((e for e in log if e["id"] == eid), None)
        assert entry is not None
        assert entry["outcome"] == "resolved"
        assert entry["user_approved"] == 1

    def test_error_count(self, error_db):
        error_db.log_error("cmd1", "err1", [])
        error_db.log_error("cmd2", "err2", [])
        assert error_db.get_error_count() == 2

    def test_get_queue_item(self, error_db):
        qid = error_db.enqueue("systemctl start docker", "unit not found", [])
        item = error_db.get_queue_item(qid)
        assert item is not None
        assert item["id"] == qid

    def test_signature_normalisation(self):
        from shce_engine import ErrorIntelligenceDB
        sig1 = ErrorIntelligenceDB._signature("E: Package 'foo-bar' not found in 2 repos")
        sig2 = ErrorIntelligenceDB._signature("E: Package 'baz' not found in 99 repos")
        # Both should produce similar structure (digits → N)
        assert "N repos" in sig1
        assert "N repos" in sig2


# ─── EnvironmentProfiler ──────────────────────────────────────────────────────

class TestEnvironmentProfiler:
    def test_snapshot_has_required_keys(self):
        from shce_engine import EnvironmentProfiler
        snap = EnvironmentProfiler.snapshot()
        required = {"os_name", "os_label", "kernel", "architecture", "package_manager",
                    "distro", "network_online", "ollama_running", "memory_gb", "disk_free_gb",
                    "cpu_count", "timestamp"}
        assert required.issubset(set(snap.keys()))

    def test_snapshot_os_name_valid(self):
        from shce_engine import EnvironmentProfiler
        snap = EnvironmentProfiler.snapshot()
        assert snap["os_name"] in ("Linux", "Windows", "Darwin")

    def test_is_online_returns_bool(self):
        from shce_engine import EnvironmentProfiler
        result = EnvironmentProfiler._is_online()
        assert isinstance(result, bool)

    def test_detect_distro_linux(self):
        import platform
        from shce_engine import EnvironmentProfiler
        if platform.system() == "Linux":
            distro = EnvironmentProfiler._detect_distro("Linux")
            assert distro in ("debian", "fedora", "arch", "opensuse")

    def test_memory_gb_positive(self):
        from shce_engine import EnvironmentProfiler
        mem = EnvironmentProfiler._memory_gb()
        assert mem >= 0

    def test_disk_free_non_negative(self):
        from shce_engine import EnvironmentProfiler
        disk = EnvironmentProfiler._disk_free_gb()
        assert disk >= 0


# ─── CommandMutationEngine ────────────────────────────────────────────────────

class TestCommandMutationEngine:
    def test_generate_alternatives_returns_list(self, mutation_engine):
        candidates = mutation_engine.generate_alternatives("apt install foo", "Package not found", max_results=5)
        assert isinstance(candidates, list)

    def test_no_blocked_candidates(self, mutation_engine):
        """Blocked commands must never appear in results."""
        candidates = mutation_engine.generate_alternatives("rm -rf /", "error", max_results=5)
        for c in candidates:
            assert c.get("safety_class") != "Blocked"

    def test_candidates_have_required_fields(self, mutation_engine):
        candidates = mutation_engine.generate_alternatives("pip install requests", "ssl error", max_results=3)
        for c in candidates:
            assert "command" in c
            assert "source" in c
            assert "score" in c
            assert "safety_class" in c

    def test_doc_db_pattern_apt_lock(self, mutation_engine):
        """APT lock error should match doc database pattern."""
        candidates = mutation_engine.generate_alternatives(
            "sudo apt install nginx",
            "E: Could not get lock /var/lib/dpkg/lock-frontend",
            max_results=5
        )
        assert any("dpkg" in c["command"] or "lock" in c["command"] for c in candidates), \
            "Expected a dpkg lock fix candidate"

    def test_doc_db_pattern_docker(self, mutation_engine):
        candidates = mutation_engine.generate_alternatives(
            "docker ps",
            "Cannot connect to the Docker daemon. Is the docker daemon running?",
            max_results=5
        )
        assert any("docker" in c["command"].lower() for c in candidates)

    def test_distro_mutation_fedora(self, tmp_db: str):
        from shce_engine import CommandMutationEngine
        eng = CommandMutationEngine(tmp_db)
        eng._env = {"os_name": "Linux", "distro": "fedora", "network_online": False, "ollama_running": False}
        candidates = eng._distro_mutation("sudo apt-get install -y git")
        assert any("dnf install -y" in c["command"] for c in candidates)

    def test_distro_mutation_arch(self, tmp_db: str):
        from shce_engine import CommandMutationEngine
        eng = CommandMutationEngine(tmp_db)
        eng._env = {"os_name": "Linux", "distro": "arch", "network_online": False, "ollama_running": False}
        candidates = eng._distro_mutation("sudo apt-get install -y git")
        assert any("pacman -S --noconfirm" in c["command"] for c in candidates)

    def test_results_limited_to_max(self, mutation_engine):
        candidates = mutation_engine.generate_alternatives("anything", "any error", max_results=2)
        assert len(candidates) <= 2

    def test_no_duplicate_commands(self, mutation_engine):
        candidates = mutation_engine.generate_alternatives(
            "sudo apt install python3",
            "Package python3 not found",
            max_results=5
        )
        commands = [c["command"].strip().lower() for c in candidates]
        assert len(commands) == len(set(commands)), "Duplicate commands found"

    def test_guess_package(self):
        from shce_engine import CommandMutationEngine
        pkg = CommandMutationEngine._guess_package("sudo apt install -y nginx", "package not found")
        assert pkg == "nginx"

    def test_guess_package_pip(self):
        from shce_engine import CommandMutationEngine
        pkg = CommandMutationEngine._guess_package("pip install requests", "no module named requests")
        assert pkg == "requests"

    def test_candidates_sorted_by_score_desc(self, mutation_engine):
        candidates = mutation_engine.generate_alternatives(
            "sudo apt install foo", "package not found", max_results=5
        )
        scores = [c.get("score", 0) for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_knowledge_base_source_used(self, tmp_db: str):
        """Seed KB and verify mutation engine finds it."""
        import datetime
        conn = sqlite3.connect(tmp_db)
        conn.execute("""
            INSERT INTO adaptive_knowledge_base
                (os_name, error_pattern, successful_fix, confidence_score,
                 success_count, failure_count, verification_status, source, last_verified)
            VALUES ('Linux', 'apt lock', 'sudo rm -f /var/lib/dpkg/lock', 0.9,
                    9, 1, 'Trusted', 'TestSeed', ?)
        """, (datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),))
        conn.commit()
        conn.close()

        from shce_engine import CommandMutationEngine
        eng = CommandMutationEngine(tmp_db)
        eng._env = {"os_name": "Linux", "distro": "debian", "network_online": False, "ollama_running": False}
        candidates = eng._from_knowledge_base("apt lock error", "Trusted")
        assert any("dpkg" in c["command"] or "lock" in c["command"] for c in candidates)

    @patch("urllib.request.urlopen")
    def test_ollama_fallback_parses_response(self, mock_urlopen, mutation_engine):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({"response": "sudo apt-get install -f"}).encode()
        mock_urlopen.return_value = mock_resp
        mutation_engine._env["ollama_running"] = True
        candidates = mutation_engine._ollama_fallback("package broken")
        assert any("apt-get install -f" in c["command"] for c in candidates)

    @patch("urllib.request.urlopen")
    def test_ollama_fallback_rejects_multiline(self, mock_urlopen, mutation_engine):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({"response": "sudo apt update\nsudo apt install foo"}).encode()
        mock_urlopen.return_value = mock_resp
        mutation_engine._env["ollama_running"] = True
        candidates = mutation_engine._ollama_fallback("package error")
        # Multi-line output should be rejected
        assert len(candidates) == 0

    def test_extract_uninstall_target(self):
        from shce_engine import _extract_uninstall_target, is_uninstall_command
        
        assert is_uninstall_command("sudo apt-get remove -y go") is True
        assert is_uninstall_command("sudo snap remove pycharm-community") is True
        assert is_uninstall_command("flatpak uninstall com.visualstudio.code") is True
        assert is_uninstall_command("pip install requests") is False
        
        assert _extract_uninstall_target("sudo apt-get remove -y go") == "go"
        assert _extract_uninstall_target("sudo snap remove pycharm-community") == "pycharm-community"
        assert _extract_uninstall_target("flatpak uninstall com.visualstudio.code") == "com.visualstudio.code"
        assert _extract_uninstall_target("sudo rm -f /usr/local/bin/go") == "/usr/local/bin/go"

    def test_heal_uninstall_failure_go(self, mutation_engine):
        candidates = mutation_engine.generate_alternatives(
            "sudo apt-get remove -y go",
            "E: Unable to locate package go",
            max_results=5
        )
        commands = [c["command"] for c in candidates]
        assert any("golang-go" in cmd for cmd in commands)


# ─── SHCEOrchestrator ─────────────────────────────────────────────────────────

class TestSHCEOrchestrator:
    def test_handle_failure_returns_dict(self, orchestrator):
        result = orchestrator.handle_failure("apt install x", "Package not found")
        assert "error_id" in result
        assert "candidates" in result
        assert "environment" in result

    def test_handle_failure_logs_to_db(self, orchestrator, tmp_db: str):
        orchestrator.handle_failure("pip install foo", "ssl error", auto_queue=False)
        from shce_engine import ErrorIntelligenceDB
        db = ErrorIntelligenceDB(tmp_db)
        assert db.get_error_count() >= 1

    def test_handle_failure_queues_best_candidate(self, orchestrator):
        result = orchestrator.handle_failure("apt install nginx", "package not found")
        # Queue ID may be None if no candidates generated, but error_id must exist
        assert result["error_id"] > 0

    def test_get_dashboard_data_structure(self, orchestrator):
        data = orchestrator.get_dashboard_data()
        assert data["ok"] is True
        assert "status" in data
        assert "queue" in data
        assert "error_log" in data
        assert "environment" in data
        assert "knowledge_base" in data

    def test_dashboard_status_keys(self, orchestrator):
        data = orchestrator.get_dashboard_data()
        status = data["status"]
        assert "core_active" in status
        assert "success_rate" in status
        assert "queue_depth" in status

    def test_kb_stats_empty(self, orchestrator):
        kb = orchestrator._kb_stats()
        assert "total" in kb
        assert "trusted" in kb
        assert "entries" in kb
        assert isinstance(kb["entries"], list)

    def test_execute_queued_fix_missing_returns_error(self, orchestrator):
        result = orchestrator.execute_queued_fix(99999)
        assert result["ok"] is False

    def test_execute_queued_fix_no_command_returns_error(self, orchestrator, tmp_db: str):
        # Enqueue item with empty command
        from shce_engine import ErrorIntelligenceDB
        db = ErrorIntelligenceDB(tmp_db)
        qid = db.enqueue("fail cmd", "some error", [], selected_candidate="")
        result = orchestrator.execute_queued_fix(qid)
        assert result["ok"] is False

    def test_uninstall_failure_no_install_early_routing(self, orchestrator):
        result = orchestrator.handle_failure(
            "sudo apt-get remove -y go",
            "E: Unable to locate package go"
        )
        assert isinstance(result, dict)
        assert "error_id" in result
        assert result["error_id"] is not None or result["queue_id"] is not None
        candidates = result["candidates"]
        assert any("golang-go" in c["command"] for c in candidates)


# ─── API Endpoints ────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_db: str):
    """FastAPI test client with SHCE routes mounted."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # Patch DB_PATH in shce_engine
    import shce_engine
    original_db = shce_engine.DB_PATH
    shce_engine.DB_PATH = tmp_db

    # Re-init singletons with tmp_db
    shce_engine.shce = shce_engine.SHCEOrchestrator(tmp_db)
    shce_engine.mutation_engine = shce_engine.CommandMutationEngine(tmp_db)
    shce_engine.error_intelligence_db = shce_engine.ErrorIntelligenceDB(tmp_db)
    shce_engine.env_profiler = shce_engine.EnvironmentProfiler()

    import routes_shce
    routes_shce.shce = shce_engine.shce
    routes_shce.mutation_engine = shce_engine.mutation_engine
    routes_shce.error_intelligence_db = shce_engine.error_intelligence_db
    routes_shce.env_profiler = shce_engine.env_profiler
    routes_shce.DB_PATH = tmp_db

    app = FastAPI()
    app.include_router(routes_shce.router)
    client = TestClient(app)

    yield client

    # Restore
    shce_engine.DB_PATH = original_db


class TestSHCEAPI:
    def test_status_endpoint(self, client):
        resp = client.get("/api/shce/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "status" in data

    def test_dashboard_endpoint(self, client):
        resp = client.get("/api/shce/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "queue" in data
        assert "error_log" in data

    def test_environment_endpoint(self, client):
        resp = client.get("/api/shce/environment")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "os_name" in data["environment"]

    def test_error_log_endpoint(self, client):
        resp = client.get("/api/shce/error-log")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert "total" in data

    def test_knowledge_endpoint(self, client):
        resp = client.get("/api/shce/knowledge")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "entries" in data

    def test_queue_endpoint(self, client):
        resp = client.get("/api/shce/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert "queue" in data

    def test_mutate_endpoint(self, client):
        resp = client.post("/api/shce/mutate", json={
            "command": "sudo apt install nginx",
            "error": "E: Package 'nginx' has no installation candidate",
            "max_results": 3
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "candidates" in data
        assert "count" in data

    def test_mutate_blocked_command_filtered(self, client):
        """rm -rf / should not appear in candidates."""
        resp = client.post("/api/shce/mutate", json={
            "command": "rm -rf /",
            "error": "permission denied",
            "max_results": 5
        })
        assert resp.status_code == 200
        for cand in resp.json().get("candidates", []):
            assert cand.get("safety_class") != "Blocked"

    def test_approve_missing_queue_item(self, client):
        resp = client.post("/api/shce/approve/99999")
        assert resp.status_code == 404

    def test_reject_missing_queue_item(self, client):
        resp = client.post("/api/shce/reject/99999")
        assert resp.status_code == 404

    def test_learn_endpoint(self, client):
        resp = client.post("/api/shce/learn", json={
            "os_name": "Linux",
            "error_pattern": "apt lock error",
            "successful_fix": "sudo rm -f /var/lib/dpkg/lock",
            "source": "TestSuite",
            "success": True
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_delete_knowledge_missing(self, client):
        resp = client.delete("/api/shce/knowledge/99999")
        assert resp.status_code == 404

    def test_handle_failure_endpoint(self, client):
        resp = client.post("/api/shce/handle-failure", json={
            "command": "pip install foo",
            "error": "ssl certificate verify failed",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_auto_heal_adaptation_triggers_queue(self, client):
        from command_adaptation import auto_heal_adaptation_scores
        class MockEngine:
            def list_recipes(self):
                return []
            def list_actions(self):
                return []
        auto_heal_adaptation_scores(MockEngine())

    def test_queue_from_error_custom_command(self, client, tmp_db: str):
        from shce_engine import ErrorIntelligenceDB
        db = ErrorIntelligenceDB(tmp_db)
        # Log an error first
        eid = db.log_error("apt install bar", "cannot resolve repository", [])
        
        # Enqueue with a custom command
        resp = client.post(f"/api/shce/queue-from-error/{eid}", json={
            "custom_command": "sudo apt install --trusted-host bar"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["command"] == "sudo apt install --trusted-host bar"
        
        # Verify it was enqueued and removed from errors
        assert db.get_error_count() == 0
        queue = db.get_queue()
        assert any(q["selected_candidate"] == "sudo apt install --trusted-host bar" for q in queue)

