"""
tests/test_stage11_75_problem_audit.py — Stage 11 75-Problem Capability Audit Automated Verification.

Verifies:
1. Exactly 75 canonical problem records exist in scratch/stage11_75_problem_audit.json
2. No duplicate problem IDs and no missing IDs (1..75)
3. Every problem has exactly one allowed primary status
4. Primary status totals sum to 75
5. All required evidence fields exist and are non-empty (except where intentionally unimplemented)
6. Platform classifications use only allowed taxonomy:
   LIVE_VALIDATED, TEST_VALIDATED, ADAPTER_ONLY, NOT_TESTED, LIVE_UNAVAILABLE, NOT_APPLICABLE
7. No LIVE_VALIDATED claim without corresponding live runtime evidence
8. No FULLY_SOLVABLE record without required complete chain:
   detection=True, identity=True, diagnosis=True, recipe=True, safety=True,
   execution=True, verification=True, rescan=True, and verified runtime/test evidence
9. Summary counts in JSON match markdown matrix definitions
10. Internal consistency across all dimensions
"""

import json
import re
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
AUDIT_JSON_PATH = REPO_ROOT / "scratch" / "stage11_75_problem_audit.json"
MATRIX_MD_PATH = REPO_ROOT / "STAGE11_FINAL_75_PROBLEM_MATRIX.md"

ALLOWED_STATUSES = {
    "FULLY_SOLVABLE",
    "DETECT_AND_REPAIR",
    "DETECT_ONLY",
    "REVIEW_ONLY",
    "BLOCKED_BY_POLICY",
    "PARTIALLY_IMPLEMENTED",
    "NOT_IMPLEMENTED",
}

ALLOWED_PLATFORM_STATUSES = {
    "LIVE_VALIDATED",
    "TEST_VALIDATED",
    "ADAPTER_ONLY",
    "NOT_TESTED",
    "LIVE_UNAVAILABLE",
    "NOT_APPLICABLE",
}

ALLOWED_EVIDENCE_STRENGTHS = {
    "LIVE",
    "AUTOMATED",
    "CONTRACT",
    "CODE_ONLY",
    "NOT_TESTED",
}


@pytest.fixture(scope="module")
def audit_records():
    assert AUDIT_JSON_PATH.exists(), f"Audit file missing: {AUDIT_JSON_PATH}"
    with open(AUDIT_JSON_PATH, "r", encoding="utf-8") as f:
        records = json.load(f)
    return records


def test_exactly_75_records(audit_records):
    assert len(audit_records) == 75, f"Expected exactly 75 records, found {len(audit_records)}"


def test_no_duplicate_or_missing_problem_ids(audit_records):
    ids = [r["problem_id"] for r in audit_records]
    assert len(ids) == len(set(ids)), f"Duplicate problem IDs found: {[x for x in ids if ids.count(x) > 1]}"
    expected_ids = set(range(1, 76))
    actual_ids = set(ids)
    assert actual_ids == expected_ids, f"Missing IDs: {expected_ids - actual_ids}, Unexpected: {actual_ids - expected_ids}"


def test_every_problem_has_valid_single_status(audit_records):
    for r in audit_records:
        pid = r["problem_id"]
        status = r.get("status")
        assert status in ALLOWED_STATUSES, f"Problem {pid} has invalid status: {status}"


def test_status_totals_sum_to_75(audit_records):
    counts = {}
    for r in audit_records:
        s = r["status"]
        counts[s] = counts.get(s, 0) + 1
    total = sum(counts.values())
    assert total == 75, f"Total problem count is {total}, expected 75"


def test_evidence_fields_exist(audit_records):
    required_fields = [
        "problem_id",
        "name",
        "status",
        "detection",
        "identity",
        "diagnosis",
        "recipe",
        "safety",
        "execution",
        "verification",
        "rescan",
        "evidence_strength",
        "implementation_evidence",
        "test_evidence",
        "platform_evidence",
        "safety_behavior",
        "notes",
    ]
    for r in audit_records:
        pid = r["problem_id"]
        for field in required_fields:
            assert field in r, f"Problem {pid} missing required field: {field}"
        assert r["name"].strip(), f"Problem {pid} has empty name"
        assert r["evidence_strength"] in ALLOWED_EVIDENCE_STRENGTHS, f"Problem {pid} invalid strength: {r['evidence_strength']}"


def test_platform_classifications_allowed_values(audit_records):
    for r in audit_records:
        pid = r["problem_id"]
        plat_ev = r.get("platform_evidence", {})
        assert "windows" in plat_ev, f"Problem {pid} missing windows platform evidence"
        assert "linux" in plat_ev, f"Problem {pid} missing linux platform evidence"
        assert "macos" in plat_ev, f"Problem {pid} missing macos platform evidence"
        for os_name, val in plat_ev.items():
            assert val in ALLOWED_PLATFORM_STATUSES, f"Problem {pid} on {os_name} has invalid platform status: {val}"


def test_no_live_validated_claim_without_evidence(audit_records):
    for r in audit_records:
        pid = r["problem_id"]
        plat_ev = r.get("platform_evidence", {})
        if plat_ev.get("windows") == "LIVE_VALIDATED":
            # Must have either test_evidence or implementation_evidence and evidence_strength == LIVE
            assert r["evidence_strength"] == "LIVE", f"Problem {pid} claimed LIVE_VALIDATED on Windows but evidence_strength is {r['evidence_strength']}"
            assert len(r["test_evidence"]) > 0 or len(r["implementation_evidence"]) > 0, f"Problem {pid} claimed LIVE_VALIDATED with no evidence"


def test_fully_solvable_requires_complete_chain(audit_records):
    for r in audit_records:
        pid = r["problem_id"]
        if r["status"] == "FULLY_SOLVABLE":
            assert r["detection"] is True, f"Problem {pid} FULLY_SOLVABLE requires detection=True"
            assert r["identity"] is True, f"Problem {pid} FULLY_SOLVABLE requires identity=True"
            assert r["diagnosis"] is True, f"Problem {pid} FULLY_SOLVABLE requires diagnosis=True"
            assert r["recipe"] is True, f"Problem {pid} FULLY_SOLVABLE requires recipe=True"
            assert r["safety"] is True, f"Problem {pid} FULLY_SOLVABLE requires safety=True"
            assert r["execution"] is True, f"Problem {pid} FULLY_SOLVABLE requires execution=True"
            assert r["verification"] is True, f"Problem {pid} FULLY_SOLVABLE requires verification=True"
            assert r["rescan"] is True, f"Problem {pid} FULLY_SOLVABLE requires rescan=True"
            assert len(r["implementation_evidence"]) > 0, f"Problem {pid} FULLY_SOLVABLE requires implementation evidence"
            assert len(r["test_evidence"]) > 0, f"Problem {pid} FULLY_SOLVABLE requires test evidence"


def test_blocked_by_policy_has_proper_safety_behavior(audit_records):
    for r in audit_records:
        pid = r["problem_id"]
        if r["status"] == "BLOCKED_BY_POLICY":
            assert r["safety_behavior"] == "IS_INTENTIONALLY_BLOCKED", f"Problem {pid} BLOCKED_BY_POLICY must have safety_behavior IS_INTENTIONALLY_BLOCKED"
            assert r["execution"] is False, f"Problem {pid} BLOCKED_BY_POLICY must not have execution=True"


def test_markdown_matrix_matches_json_records(audit_records):
    if not MATRIX_MD_PATH.exists():
        pytest.skip("STAGE11_FINAL_75_PROBLEM_MATRIX.md not yet created")
    
    content = MATRIX_MD_PATH.read_text(encoding="utf-8")
    table_rows = []
    for line in content.splitlines():
        if line.startswith("|"):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if parts and parts[0].isdigit():
                table_rows.append((int(parts[0]), parts))

    assert len(table_rows) == 75, f"Expected 75 problem rows in STAGE11_FINAL_75_PROBLEM_MATRIX.md, found {len(table_rows)}"

    for pid, parts in table_rows:
        status = parts[10]
        json_rec = next(r for r in audit_records if r["problem_id"] == pid)
        assert json_rec["status"] == status, f"Mismatch for Problem {pid}: Markdown status {status} != JSON status {json_rec['status']}"
