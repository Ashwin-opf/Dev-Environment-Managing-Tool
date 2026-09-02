"""
Live HTTP Test Runner for DevTools & Control Center Standalone Application
"""

import os
import sys
import time
import json
import threading
from pathlib import Path

# Add backend to sys.path
BACKEND_DIR = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import uvicorn
import requests

from main import app

TEST_PORT = 8798
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"


def run_server():
    uvicorn.run(app, host="127.0.0.1", port=TEST_PORT, log_level="warning")


def main():
    print("=" * 60)
    print(" DEVTOOLS & CONTROL CENTER — STANDALONE TEST SUITE")
    print("=" * 60)

    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait for server to become healthy
    ready = False
    for _ in range(30):
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=1)
            if r.status_code == 200 and r.json().get("status") == "healthy":
                ready = True
                break
        except Exception:
            time.sleep(0.3)

    if not ready:
        print("[FAIL] Server did not start within timeout.")
        sys.exit(1)

    print("[OK] Test Server is live at", BASE_URL)

    passed = 0
    failed = 0

    def test(name, fn):
        nonlocal passed, failed
        try:
            fn()
            print(f"  ✓ PASS: {name}")
            passed += 1
        except Exception as e:
            print(f"  ✗ FAIL: {name} — {e}")
            failed += 1

    # 1. Health & Status
    def t_health():
        r = requests.get(f"{BASE_URL}/health")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "healthy"
        assert d["service"] == "devtools-control-center"
        assert "os" in d

    def t_system_status():
        r = requests.get(f"{BASE_URL}/api/status/system")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    # 2. Frontend Assets
    def t_frontend_index():
        r = requests.get(f"{BASE_URL}/")
        assert r.status_code == 200
        assert "DevTools Store & Control Center" in r.text
        assert "app-shell" in r.text

    def t_frontend_static():
        r = requests.get(f"{BASE_URL}/style.css")
        assert r.status_code == 200
        assert "var(--surface-1)" in r.text

    # 3. Control Center Flow
    def t_control_center_flow():
        # Enqueue
        enq = requests.post(f"{BASE_URL}/api/control-center/enqueue", json={
            "command": "winget install --id Git.Git -e --silent",
            "target": "Git CLI",
            "risk_tier": "Medium",
            "risk_reasons": ["Environment variable modification"],
            "source": "devtools",
        }).json()
        assert enq.get("ok") is True
        aid = enq["action_id"]

        # Check queue
        q = requests.get(f"{BASE_URL}/api/control-center/queue?status=pending").json()
        assert q["ok"] is True
        found = [x for x in q["items"] if x["action_id"] == aid]
        assert len(found) == 1
        assert found[0]["target"] == "Git CLI"

        # Approve
        appr = requests.post(f"{BASE_URL}/api/control-center/approve", json={"action_id": aid}).json()
        assert appr["ok"] is True
        assert appr["status"] == "approved"

        # Audit
        aud = requests.get(f"{BASE_URL}/api/control-center/audit?search=Git").json()
        assert aud["ok"] is True
        assert any(x["action_id"] == aid for x in aud["entries"])

        # Enqueue & Reject
        enq2 = requests.post(f"{BASE_URL}/api/control-center/enqueue", json={
            "command": "del /f /q test.dll",
            "target": "Test File",
            "risk_tier": "High",
            "source": "test",
        }).json()
        aid2 = enq2["action_id"]

        rej = requests.post(f"{BASE_URL}/api/control-center/reject", json={"action_id": aid2}).json()
        assert rej["ok"] is True
        assert rej["status"] == "rejected"

    # 4. Trust Tiers
    def t_trust_tiers():
        tiers = requests.get(f"{BASE_URL}/api/control-center/trust-tiers").json()
        assert tiers["ok"] is True

        up = requests.post(f"{BASE_URL}/api/control-center/trust-tiers", json={
            "category": "devtools_install",
            "level": "always_require_approval",
        }).json()
        assert up["ok"] is True
        assert up["level"] == "always_require_approval"

    # 5. Snapshots & Rollback
    def t_snapshots():
        snap = requests.post(f"{BASE_URL}/api/control-center/snapshots?label=IntegrationTestSnap").json()
        assert snap["ok"] is True
        sid = snap["snapshot"]["id"]

        snaps = requests.get(f"{BASE_URL}/api/control-center/snapshots").json()
        assert snaps["ok"] is True
        assert any(s["id"] == sid for s in snaps["snapshots"])

        rev = requests.post(f"{BASE_URL}/api/control-center/revert", json={"snapshot_id": sid}).json()
        assert "success" in rev or "ok" in rev

    # 6. DevTools Catalog & Status
    def t_devtools_catalog():
        r = requests.get(f"{BASE_URL}/api/devtools/catalog").json()
        assert r["ok"] is True
        assert len(r["tools"]) >= 10
        names = [t["name"] for t in r["tools"]]
        assert "Python" in names
        assert "Git" in names
        assert "Docker" in names
        assert "VS Code" in names

    def t_devtools_status():
        r = requests.get(f"{BASE_URL}/api/devtools/status").json()
        assert r["ok"] is True
        assert "python3" in r["status"]

    # 7. DevTools Extract
    def t_devtools_extract():
        r = requests.post(f"{BASE_URL}/api/devtools/extract", json={"app": "Python"}).json()
        assert r["ok"] is True
        assert "command" in r
        assert "risk" in r
        assert "Python" in r["title"]

    # 8. DevTools Resolution Pipeline
    def t_devtools_resolve():
        r = requests.post(f"{BASE_URL}/api/devtools/resolve", json={
            "query": "python",
            "variant": "",
            "force_refresh": False,
        }).json()
        assert r["ok"] is True
        assert "status" in r
        assert "candidates" in r
        assert len(r["candidates"]) > 0

    # 9. DevTools Package Details
    def t_devtools_pkg_details():
        r = requests.post(f"{BASE_URL}/api/devtools/package-details", json={
            "id": "Python.Python.3.12",
            "manager": "winget",
        }).json()
        assert r["ok"] is True
        assert "install_cmd" in r

    # 10. DevTools Version & Uninstall Commands
    def t_devtools_helper_cmds():
        v = requests.get(f"{BASE_URL}/api/devtools/version-cmd?name=git").json()
        assert v["ok"] is True
        assert v["found"] is True

        u = requests.get(f"{BASE_URL}/api/devtools/uninstall-cmd?tool=git").json()
        assert u["ok"] is True
        assert "command" in u

    # 11. DevTools Managed Apps Lifecycle
    def t_devtools_managed_lifecycle():
        rec = requests.post(f"{BASE_URL}/api/devtools/resolve/record-install", json={
            "query": "git",
            "pkg_id": "Git.Git",
            "manager": "winget",
            "source": "winget",
            "publisher": "Git Project",
            "success": True,
        }).json()
        assert rec["ok"] is True

        apps = requests.get(f"{BASE_URL}/api/devtools/managed").json()
        assert apps["ok"] is True
        assert any(a["app_id"] == "Git.Git" for a in apps["apps"])

        unin = requests.post(f"{BASE_URL}/api/devtools/uninstall", json={
            "app_id": "Git.Git",
            "confirm": True,
        }).json()
        assert unin["ok"] is True

    # 12. DevTools SSE Update Stream
    def t_devtools_update_stream():
        r = requests.get(f"{BASE_URL}/api/devtools/update-stream?app_id=python3", stream=True)
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        # Read first SSE chunk
        for chunk in r.iter_lines():
            if chunk:
                line = chunk.decode("utf-8")
                if line.startswith("data:"):
                    d = json.loads(line[5:].strip())
                    assert "phase" in d
                    assert "pct" in d
                    break

    # 13. Control Center Batch Actions
    def t_batch_actions():
        requests.post(f"{BASE_URL}/api/control-center/enqueue", json={
            "command": "echo 'batch live test'",
            "target": "Batch Tool Live",
            "risk_tier": "Low",
            "source": "test",
        })
        b = requests.post(f"{BASE_URL}/api/control-center/batch-approve?risk_tier=Low").json()
        assert b["ok"] is True
        assert b["approved_count"] >= 1

    # 14. Audit Export
    def t_audit_export():
        r_csv = requests.get(f"{BASE_URL}/api/control-center/audit/export?format=csv")
        assert r_csv.status_code == 200
        assert "Action ID,Decision" in r_csv.text

        r_json = requests.get(f"{BASE_URL}/api/control-center/audit/export?format=json")
        assert r_json.status_code == 200
        assert isinstance(r_json.json(), list)

    # 15. Snapshot Diff
    def t_snapshot_diff():
        s1 = requests.post(f"{BASE_URL}/api/control-center/snapshots?label=LiveDiff1").json()["snapshot"]["id"]
        s2 = requests.post(f"{BASE_URL}/api/control-center/snapshots?label=LiveDiff2").json()["snapshot"]["id"]
        diff = requests.get(f"{BASE_URL}/api/control-center/snapshots/diff?snap_1={s1}&snap_2={s2}").json()
        assert diff["ok"] is True
        assert "package_diff" in diff

    # 16. Dev Doctor & Stacks
    def t_dev_doctor():
        doc = requests.get(f"{BASE_URL}/api/devtools/doctor").json()
        assert doc["ok"] is True
        assert "health_score" in doc
        assert len(doc["stacks"]) >= 4

    # 17. RAG Semantic Knowledge Search
    def t_rag_knowledge():
        rag = requests.get(f"{BASE_URL}/api/devtools/rag/query?q=pip").json()
        assert rag["ok"] is True
        assert "results" in rag
        assert isinstance(rag["results"], list)

    # 18. Automatic Repair Finder
    def t_auto_repair():
        rep = requests.get(f"{BASE_URL}/api/devtools/repair/find").json()
        assert rep["ok"] is True
        assert "repairs" in rep
        assert isinstance(rep["repairs"], list)

    # 19. Sandbox Dry-Run Simulation
    def t_sandbox_dry_run():
        sb = requests.post(f"{BASE_URL}/api/devtools/sandbox/dry-run", json={
            "command": "pip install --upgrade pytest",
            "target": "Pytest Upgrade",
        }).json()
        assert sb["ok"] is True
        assert "sandbox_result" in sb
        assert "risk_tier" in sb
        assert "blast_radius" in sb

    # 20. Live Command Execution Stream
    def t_execute_stream():
        r = requests.post(f"{BASE_URL}/api/devtools/execute-stream", json={
            "command": "python -c \"print('live stream check')\"",
            "target": "Test",
        }, stream=True)
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        # Read first SSE chunk
        for chunk in r.iter_lines():
            if chunk:
                line = chunk.decode("utf-8")
                if line.startswith("data:"):
                    d = json.loads(line[5:].strip())
                    assert "type" in d
                    break

    # Run tests
    print("\n--- Running Core & Custom Feature Tests ---")
    test("Health Check Endpoint", t_health)
    test("System Status Endpoint", t_system_status)
    test("Frontend Index Serving", t_frontend_index)
    test("Frontend CSS Static Serving", t_frontend_static)
    test("Control Center Action Approval & Rejection Flow", t_control_center_flow)
    test("Control Center Trust Tier Policies", t_trust_tiers)
    test("Control Center System Snapshots & Revert", t_snapshots)
    test("DevTools Catalog API", t_devtools_catalog)
    test("DevTools Status Detection Probe", t_devtools_status)
    test("DevTools Recipe Extraction & Risk Assessment", t_devtools_extract)
    test("DevTools Package Resolution Pipeline", t_devtools_resolve)
    test("DevTools Package Details API", t_devtools_pkg_details)
    test("DevTools Helper Commands (Version & Uninstall)", t_devtools_helper_cmds)
    test("DevTools Managed Apps Lifecycle (Install, List, Uninstall)", t_devtools_managed_lifecycle)
    test("DevTools SSE Real-Time Update Stream", t_devtools_update_stream)
    test("Control Center Batch Approvals", t_batch_actions)
    test("Control Center Audit Trail Export (CSV/JSON)", t_audit_export)
    test("Control Center Snapshot Diff Comparator", t_snapshot_diff)
    test("Dev Environment Doctor Diagnostics & Stacks", t_dev_doctor)
    test("RAG Semantic Knowledge Search", t_rag_knowledge)
    test("Dev Environment Auto-Repair Finder", t_auto_repair)
    test("Sandbox Dry-Run Simulation Engine", t_sandbox_dry_run)
    test("Live Command Execution Terminal Stream", t_execute_stream)


    print("\n" + "=" * 60)
    print(f" RESULTS: {passed} PASSED, {failed} FAILED (Total: {passed + failed})")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)
    else:
        print("\nALL 21 TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)


if __name__ == "__main__":
    main()

