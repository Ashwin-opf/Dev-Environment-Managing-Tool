"""
Comprehensive Test Suite for DevTools & Control Center Standalone API
"""

import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Add backend directory to sys.path
BACKEND_DIR = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ─── 1. Health & Diagnostic Endpoints ─────────────────────────────────────────

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "devtools-control-center"
    assert "os" in data


def test_system_status(client):
    response = client.get("/api/status/system")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "os" in data
    assert "architecture" in data
    assert "active_package_managers" in data


# ─── 2. Control Center Endpoints ──────────────────────────────────────────────

def test_control_center_flow(client):
    # 1. Enqueue action
    action_payload = {
        "command": "winget install --id Git.Git -e --silent",
        "target": "Git",
        "risk_tier": "Medium",
        "risk_reasons": ["Modifies environment PATH"],
        "source": "devtools",
    }
    enq_res = client.post("/api/control-center/enqueue", json=action_payload)
    assert enq_res.status_code == 200
    enq_data = enq_res.json()
    assert enq_data["ok"] is True
    action_id = enq_data["action_id"]

    # 2. Query queue
    q_res = client.get("/api/control-center/queue?status=pending")
    assert q_res.status_code == 200
    q_data = q_res.json()
    assert q_data["ok"] is True
    matching = [item for item in q_data["items"] if item["action_id"] == action_id]
    assert len(matching) == 1
    assert matching[0]["target"] == "Git"

    # 3. Approve action
    appr_res = client.post("/api/control-center/approve", json={"action_id": action_id, "reason": "Verified safe"})
    assert appr_res.status_code == 200
    assert appr_res.json()["ok"] is True

    # 4. Check audit trail
    audit_res = client.get(f"/api/control-center/audit?search=Git")
    assert audit_res.status_code == 200
    audit_data = audit_res.json()
    assert audit_data["ok"] is True
    assert any(entry.get("action_id") == action_id for entry in audit_data["entries"])

    # 5. Enqueue and reject another action
    rej_enq = client.post("/api/control-center/enqueue", json={
        "command": "del /f /q C:\\Windows\\System32\\driver.dll",
        "target": "Driver System File",
        "risk_tier": "High",
        "risk_reasons": ["Deletes system file"],
        "source": "test",
    }).json()
    rej_id = rej_enq["action_id"]

    rej_res = client.post("/api/control-center/reject", json={"action_id": rej_id, "reason": "Blocked unsafe command"})
    assert rej_res.status_code == 200
    assert rej_res.json()["ok"] is True


def test_trust_tiers(client):
    # Get trust tiers
    res = client.get("/api/control-center/trust-tiers")
    assert res.status_code == 200
    assert res.json()["ok"] is True

    # Update trust tier
    up_res = client.post("/api/control-center/trust-tiers", json={
        "category": "devtools_install",
        "level": "always_require_approval",
    })
    assert up_res.status_code == 200
    assert up_res.json()["level"] == "always_require_approval"


def test_snapshots(client):
    # Create manual snapshot
    create_res = client.post("/api/control-center/snapshots?label=Test%20Snapshot")
    assert create_res.status_code == 200
    data = create_res.json()
    assert data["ok"] is True
    snap_id = data["snapshot"]["id"]

    # List snapshots
    list_res = client.get("/api/control-center/snapshots")
    assert list_res.status_code == 200
    snaps = list_res.json()["snapshots"]
    assert any(s["id"] == snap_id for s in snaps)

    # Revert to snapshot
    rev_res = client.post("/api/control-center/revert", json={"snapshot_id": snap_id})
    assert rev_res.status_code == 200


# ─── 3. DevTools Endpoints ───────────────────────────────────────────────────

def test_devtools_catalog_and_status(client):
    # Catalog
    cat_res = client.get("/api/devtools/catalog")
    assert cat_res.status_code == 200
    cat_data = cat_res.json()
    assert cat_data["ok"] is True
    assert len(cat_data["tools"]) > 0

    # Status
    status_res = client.get("/api/devtools/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["ok"] is True
    assert "python3" in status_data["status"]


def test_devtools_extract_and_dryrun(client):
    res = client.post("/api/devtools/extract", json={"app": "Python"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "command" in data
    assert "risk" in data


def test_devtools_resolve_pipeline(client):
    res = client.post("/api/devtools/resolve", json={"query": "python", "variant": "", "force_refresh": False})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "status" in data
    assert "candidates" in data


def test_devtools_version_and_uninstall_cmds(client):
    # Version command probe
    ver_res = client.get("/api/devtools/version-cmd?name=git")
    assert ver_res.status_code == 200
    assert ver_res.json()["ok"] is True

    # Uninstall command probe
    uninst_res = client.get("/api/devtools/uninstall-cmd?tool=git")
    assert uninst_res.status_code == 200
    assert uninst_res.json()["ok"] is True


def test_devtools_managed_apps_and_lifecycle(client):
    # Record install into managed apps
    rec_res = client.post("/api/devtools/resolve/record-install", json={
        "query": "git",
        "pkg_id": "Git.Git",
        "manager": "winget",
        "source": "winget",
        "publisher": "Git Project",
        "success": True,
    })
    assert rec_res.status_code == 200
    assert rec_res.json()["recorded"] is True

    # List managed apps
    list_res = client.get("/api/devtools/managed")
    assert list_res.status_code == 200
    apps = list_res.json()["apps"]
    assert any(a["app_id"] == "Git.Git" for a in apps)

    # Uninstall managed app
    del_res = client.post("/api/devtools/uninstall", json={"app_id": "Git.Git", "confirm": True})
    assert del_res.status_code == 200
    assert del_res.json()["ok"] is True


def test_devtools_update_stream(client):
    with client.stream("GET", "/api/devtools/update-stream?app_id=python") as res:
        assert res.status_code == 200
        assert "text/event-stream" in res.headers["content-type"]
        for line in res.iter_lines():
            if line:
                break



# ─── 4. Custom Features Tests ────────────────────────────────────────────────

def test_control_center_batch_actions(client):
    # Enqueue two test actions
    client.post("/api/control-center/enqueue", json={
        "command": "echo 'batch test 1'",
        "target": "Batch Tool 1",
        "risk_tier": "Low",
        "source": "test",
    })
    client.post("/api/control-center/enqueue", json={
        "command": "echo 'batch test 2'",
        "target": "Batch Tool 2",
        "risk_tier": "Low",
        "source": "test",
    })

    # Batch approve
    b_appr = client.post("/api/control-center/batch-approve?risk_tier=Low")
    assert b_appr.status_code == 200
    data = b_appr.json()
    assert data["ok"] is True
    assert data["approved_count"] >= 2

    # Enqueue and batch reject
    client.post("/api/control-center/enqueue", json={
        "command": "echo 'batch reject test'",
        "target": "Batch Reject Tool",
        "risk_tier": "High",
        "source": "test",
    })
    b_rej = client.post("/api/control-center/batch-reject?risk_tier=High")
    assert b_rej.status_code == 200
    assert b_rej.json()["ok"] is True
    assert b_rej.json()["rejected_count"] >= 1


def test_control_center_audit_export(client):
    # Export as JSON
    res_json = client.get("/api/control-center/audit/export?format=json")
    assert res_json.status_code == 200
    assert "application/json" in res_json.headers["content-type"]
    assert "control_center_audit.json" in res_json.headers["content-disposition"]

    # Export as CSV
    res_csv = client.get("/api/control-center/audit/export?format=csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["content-type"]
    assert "Action ID,Decision" in res_csv.text


def test_snapshot_diff(client):
    snap1 = client.post("/api/control-center/snapshots?label=DiffSnap1").json()["snapshot"]
    snap2 = client.post("/api/control-center/snapshots?label=DiffSnap2").json()["snapshot"]

    diff_res = client.get(f"/api/control-center/snapshots/diff?snap_1={snap1['id']}&snap_2={snap2['id']}")
    assert diff_res.status_code == 200
    d = diff_res.json()
    assert d["ok"] is True
    assert "package_diff" in d
    assert "env_diff" in d


def test_dev_doctor(client):
    res = client.get("/api/devtools/doctor")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "health_score" in data
    assert 0 <= data["health_score"] <= 100
    assert len(data["checks"]) > 0
    assert len(data["stacks"]) >= 4
    stack_names = [s["name"] for s in data["stacks"]]
    assert "Fullstack Web & JavaScript" in stack_names
    assert "Python AI & Data Science" in stack_names


def test_rag_knowledge_query(client):
    res = client.get("/api/devtools/rag/query?q=pip")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "results" in data
    assert isinstance(data["results"], list)


def test_auto_repair_finder(client):
    res = client.get("/api/devtools/repair/find")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "repairs" in data
    assert "os" in data
    assert isinstance(data["repairs"], list)


def test_sandbox_dry_run(client):
    res = client.post("/api/devtools/sandbox/dry-run", json={
        "command": "npm install -g typescript",
        "target": "TypeScript Global CLI",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "sandbox_result" in data
    assert "risk_tier" in data
    assert "blast_radius" in data



def test_execute_command_stream(client):
    res = client.post("/api/devtools/execute-stream", json={
        "command": "python -c \"print('live terminal output line 1')\"",
        "target": "Test Run",
    })
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

