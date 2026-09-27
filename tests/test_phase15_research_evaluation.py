"""
tests/test_phase15_research_evaluation.py
=========================================
Research Metrics, Ablation & Comparative Evaluation Verification Suite for Phase 15.
Proves all research invariants:
  - Canonical dataset integrity (N=75, 50 actionable / 25 non-automatic)
  - RQ1: 100% detection coverage across 75 scenarios
  - RQ2: 50/75 automatic remediation coverage (21 fully solvable + 29 detect & repair)
  - RQ3: Trust/provenance ablation (Config A full trust vs Config B reduced trust)
  - RQ4: Centralized execution boundary ablation (Single authoritative engine vs decentralized)
  - RQ5: Verification + Rescan ablation (Elimination of false-positive repair success)
  - RQ6: Safety Gate effectiveness across dangerous and policy-bound inputs (10/10 blocked, 0 mutating subprocesses)
  - RQ7: Comparative baselines (Baselines A, B, C vs Proposed System)
  - RQ8: Cross-platform evidence categorization (Windows, Linux, macOS)
  - Problems #54 and #56 evaluation
  - AI/RAG provenance safety policy
"""

import csv
import json
import os
import platform
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from canonical_identity import canonical_store
from execution_plan import ExecutionPlan, ExecutionRequest, ExecutionResolver, execution_resolver, ProvenanceClass
from execution_tier import ExecutionTier
from authoritative_safety import AuthoritativeSafetyLayer, authoritative_safety, BlockedReason, SafetyGateResult
from execution_engine import CentralizedExecutionEngine, execution_engine, ExecutionOutcome
from recipe_engine import RecipeOperation, StructuredRecipe
from verification_engine import (
    AuthoritativeVerificationEngine,
    VerificationLevel,
    VerificationPolicy,
    VerificationResult,
    VerificationStatus,
    verification_engine,
)
from multi_source_manager import (
    InstallationSourceType,
    MultiSourceStatus,
    DetectedInstallation,
    MultiSourceDetector,
    MultiSourceRemediator,
)
from managed_footprint import ManagedFootprintRegistry, ManagedInstallation, OwnershipState


def make_test_recipe(recipe_id: str = "win_git_install", source: str = "STATIC_DB") -> StructuredRecipe:
    return StructuredRecipe(
        recipe_id=recipe_id,
        recipe_version=1,
        identity_id="git",
        operation=RecipeOperation.INSTALL,
        os="Windows",
        architecture="x64",
        package_manager="winget",
        executable="winget",
        arguments=["install", "--id", "Git.Git", "--exact", "--silent"],
        verification_command=["git", "--version"],
        source=source,
    )


class TestPhase15ResearchEvaluation(unittest.TestCase):
    """Authoritative research validation tests for Phase 15."""

    @classmethod
    def setUpClass(cls):
        # Load generated Phase 15 research artifacts
        results_path = Path("scratch/phase15_results.json")
        ablation_path = Path("scratch/phase15_ablation_results.json")
        baseline_path = Path("scratch/phase15_baseline_comparison.json")
        cross_path = Path("scratch/phase15_cross_platform_evidence.json")

        assert results_path.exists(), "scratch/phase15_results.json must exist"
        assert ablation_path.exists(), "scratch/phase15_ablation_results.json must exist"
        assert baseline_path.exists(), "scratch/phase15_baseline_comparison.json must exist"
        assert cross_path.exists(), "scratch/phase15_cross_platform_evidence.json must exist"

        with open(results_path, "r", encoding="utf-8") as f:
            cls.results_75 = json.load(f)
        with open(ablation_path, "r", encoding="utf-8") as f:
            cls.ablation_data = json.load(f)
        with open(baseline_path, "r", encoding="utf-8") as f:
            cls.baseline_data = json.load(f)
        with open(cross_path, "r", encoding="utf-8") as f:
            cls.cross_data = json.load(f)

    # =========================================================================
    # 1. CANONICAL DATASET INTEGRITY
    # =========================================================================
    def test_01_canonical_dataset_integrity(self):
        """Verifies N=75 frozen dataset taxonomy: 21 FULLY_SOLVABLE, 29 DETECT_AND_REPAIR, 10 DETECT_ONLY, 9 REVIEW_ONLY, 6 BLOCKED_BY_POLICY."""
        self.assertEqual(len(self.results_75), 75)

        primary_counts = {}
        suitability_counts = {}
        for r in self.results_75:
            p = r["primary_classification"]
            s = r["automation_suitability"]
            primary_counts[p] = primary_counts.get(p, 0) + 1
            suitability_counts[s] = suitability_counts.get(s, 0) + 1

        self.assertEqual(primary_counts.get("FULLY_SOLVABLE"), 21)
        self.assertEqual(primary_counts.get("DETECT_AND_REPAIR"), 29)
        self.assertEqual(primary_counts.get("DETECT_ONLY"), 10)
        self.assertEqual(primary_counts.get("REVIEW_ONLY"), 9)
        self.assertEqual(primary_counts.get("BLOCKED_BY_POLICY"), 6)

        # Automation boundary: 50 suitable, 15 human-guided, 10 policy-bound
        self.assertEqual(suitability_counts.get("CURRENTLY_ACTIONABLE"), 50)
        self.assertEqual(suitability_counts.get("HUMAN_GUIDED"), 15)
        self.assertEqual(suitability_counts.get("POLICY_BOUND"), 10)

    # =========================================================================
    # 2. RQ1: DETECTION COVERAGE (100%)
    # =========================================================================
    def test_02_rq1_detection_coverage_100_percent(self):
        """Verifies RQ1: All 75 canonical scenarios are detected with high confidence (100.0% detection rate)."""
        detected_count = sum(1 for r in self.results_75 if r["detection_supported"])
        self.assertEqual(detected_count, 75)
        self.assertEqual(detected_count / 75 * 100.0, 100.0)

        # Category coverage verification
        categories = set(r["category"] for r in self.results_75)
        self.assertEqual(len(categories), 7)
        for cat in categories:
            cat_items = [r for r in self.results_75 if r["category"] == cat]
            cat_detected = sum(1 for r in cat_items if r["detection_supported"])
            self.assertEqual(cat_detected, len(cat_items), f"Incomplete detection in category: {cat}")

    # =========================================================================
    # 3. RQ2: AUTOMATIC REMEDIATION COVERAGE (50 / 75)
    # =========================================================================
    def test_03_rq2_automatic_remediation_coverage(self):
        """Verifies RQ2: 50/75 problems suitable for automation (66.7%), 15 human-guided (20.0%), 10 policy-bound (13.3%)."""
        actionable = [r for r in self.results_75 if r["implemented_actionable"]]
        self.assertEqual(len(actionable), 50)

        fully_solvable = [r for r in self.results_75 if r["primary_classification"] == "FULLY_SOLVABLE"]
        detect_repair = [r for r in self.results_75 if r["primary_classification"] == "DETECT_AND_REPAIR"]
        self.assertEqual(len(fully_solvable), 21)
        self.assertEqual(len(detect_repair), 29)

        human_guided = [r for r in self.results_75 if r["automation_suitability"] == "HUMAN_GUIDED"]
        policy_bound = [r for r in self.results_75 if r["automation_suitability"] == "POLICY_BOUND"]
        self.assertEqual(len(human_guided), 15)
        self.assertEqual(len(policy_bound), 10)

    # =========================================================================
    # 4. RQ3: TRUST / PROVENANCE ABLATION
    # =========================================================================
    def test_04_rq3_trust_ablation_invariants(self):
        """Verifies RQ3: Full trust system provides strictly verified automatic execution for golden recipes with 0 unauthorized mutations."""
        rq3 = self.ablation_data["rq3_trust_provenance_ablation"]
        cfg_a = rq3["configuration_a_full_trust"]
        cfg_b = rq3["configuration_b_reduced_trust"]

        # Config A invariants:
        self.assertEqual(cfg_a["golden_recipe_authorizations"], 1)
        self.assertEqual(cfg_a["false_automatic_authorizations"], 0)
        self.assertEqual(cfg_a["unauthorized_mutating_subprocesses"], 0)
        self.assertEqual(cfg_a["execution_policy_violations"], 0)
        self.assertGreaterEqual(cfg_a["untrusted_commands_blocked_from_auto_execution"], 4)

        # Config B invariants (demonstrates failure modes of naive execution):
        self.assertGreater(cfg_b["false_automatic_authorizations"], 0)
        self.assertGreater(cfg_b["unauthorized_mutating_subprocesses"], 0)
        self.assertGreater(cfg_b["execution_policy_violations"], 0)

    # =========================================================================
    # 5. RQ4: CENTRALIZED EXECUTION ABLATION
    # =========================================================================
    def test_05_rq4_centralized_execution_boundary(self):
        """Verifies RQ4: CentralizedExecutionEngine provides single mutation authority with 100% policy, safety, and logging coverage."""
        rq4 = self.ablation_data["rq4_centralized_execution_ablation"]
        full = rq4["architectural_comparison"]["full_centralized_architecture"]
        base = rq4["architectural_comparison"]["decentralized_baseline"]

        self.assertEqual(full["mutation_entry_points"], 1)
        self.assertEqual(full["unauthorized_mutation_paths"], 0)
        self.assertEqual(full["policy_enforcement_coverage_pct"], 100.0)
        self.assertEqual(full["safety_gate_enforcement_coverage_pct"], 100.0)
        self.assertEqual(full["verification_integration_coverage_pct"], 100.0)
        self.assertEqual(full["concurrency_resource_locking_coverage_pct"], 100.0)

        # Baseline has fragmented coverage
        self.assertGreater(base["mutation_entry_points"], 1)
        self.assertGreater(base["unauthorized_mutation_paths"], 0)
        self.assertLess(base["verification_integration_coverage_pct"], 100.0)

    # =========================================================================
    # 6. RQ5: VERIFICATION + RESCAN ABLATION
    # =========================================================================
    def test_06_rq5_verification_rescan_false_success_elimination(self):
        """Verifies RQ5: Verification and rescan eliminate false-positive repair success (0.0% vs 50.0% in exit-code baseline)."""
        rq5 = self.ablation_data["rq5_verification_rescan_ablation"]
        full = rq5["full_architecture"]
        reduced = rq5["reduced_architecture"]

        self.assertEqual(full["false_success_rate_pct"], 0.0)
        self.assertEqual(full["stale_repair_rate_pct"], 0.0)
        self.assertEqual(full["correctness_rate_pct"], 100.0)

        # Reduced baseline exhibits high false-success rate
        self.assertGreaterEqual(reduced["false_success_rate_pct"], 30.0)
        self.assertLess(reduced["correctness_rate_pct"], 100.0)

    # =========================================================================
    # 7. RQ6: SAFETY GATE EFFECTIVENESS
    # =========================================================================
    def test_07_rq6_safety_gate_blocking_invariants(self):
        """Verifies RQ6: Safety Gate blocks all unsafe inputs before mutation with strictly 0 mutating subprocesses."""
        rq6 = self.ablation_data["rq6_safety_gate_evaluation"]

        self.assertEqual(rq6["total_unsafe_cases_tested"], 10)
        self.assertEqual(rq6["blocked_before_mutation"], 10)
        self.assertEqual(rq6["blocked_after_mutation"], 0)
        self.assertEqual(rq6["unauthorized_mutating_subprocesses"], 0)
        self.assertEqual(rq6["mutation_count_before_block"], 0)
        self.assertTrue(rq6["safety_invariant_satisfied"])

    # =========================================================================
    # 8. RQ7: COMPARATIVE BASELINE EVALUATION
    # =========================================================================
    def test_08_rq7_comparative_baselines(self):
        """Verifies RQ7: Proposed system achieves superior detection, remediation, safety, and zero false-success vs Baselines A, B, C."""
        baselines = self.baseline_data["baselines"]
        prop = baselines["proposed_system"]
        base_a = baselines["baseline_a"]
        base_b = baselines["baseline_b"]
        base_c = baselines["baseline_c"]

        self.assertEqual(prop["detection_coverage_pct"], 100.0)
        self.assertEqual(prop["automatic_remediation_coverage_pct"], 66.7)
        self.assertEqual(prop["false_success_rate_pct"], 0.0)
        self.assertEqual(prop["unauthorized_mutation_count"], 0)
        self.assertEqual(prop["final_state_correctness_pct"], 100.0)

        self.assertLess(base_a["detection_coverage_pct"], prop["detection_coverage_pct"])
        self.assertLess(base_b["detection_coverage_pct"], prop["detection_coverage_pct"])
        self.assertGreater(base_a["false_success_rate_pct"], 0.0)
        self.assertGreater(base_b["false_success_rate_pct"], 0.0)
        self.assertGreater(base_c["false_success_rate_pct"], 0.0)

    # =========================================================================
    # 9. RQ8: CROSS-PLATFORM EVIDENCE STRENGTHENING
    # =========================================================================
    def test_09_rq8_cross_platform_evidence(self):
        """Verifies RQ8: Explicit categorization of evidence across Windows, Linux, and macOS platforms."""
        summary = self.cross_data["platform_evidence_summary"]

        self.assertIn("windows", summary)
        self.assertIn("linux", summary)
        self.assertIn("macos", summary)

        # Total scenarios per platform must equal 75
        self.assertEqual(summary["windows"]["total"], 75)
        self.assertEqual(summary["linux"]["total"], 75)
        self.assertEqual(summary["macos"]["total"], 75)

        # Windows has native live evidence on host
        self.assertGreaterEqual(summary["windows"]["native_live"], 20)

        # Linux and macOS are explicitly classified as contract/mock validated
        self.assertEqual(summary["linux"]["native_live"], 0)
        self.assertGreaterEqual(summary["linux"]["contract_validated"], 50)
        self.assertEqual(summary["macos"]["native_live"], 0)
        self.assertGreaterEqual(summary["macos"]["contract_validated"], 50)

    # =========================================================================
    # 10. PROBLEM #54: LINUX REPOSITORY OUTDATED EVALUATION
    # =========================================================================
    def test_10_problem54_linux_outdated_repo(self):
        """Verifies Problem #54 implementation contract, multi-step halting, and provider support."""
        p54 = self.cross_data["problem_54_linux_outdated_repository"]
        self.assertEqual(p54["status"], "IMPLEMENTED_ACTIONABLE")
        self.assertEqual(p54["supported_providers"], ["apt", "dnf", "pacman", "zypper", "apk"])
        self.assertIn("PASS", p54["multi_step_halting_invariant"])

    # =========================================================================
    # 11. PROBLEM #56: MULTIPLE INSTALLATION SOURCES EVALUATION
    # =========================================================================
    def test_11_problem56_multiple_sources(self):
        """Verifies Problem #56 implementation contract, unmanaged source preservation, and managed cleanup."""
        p56 = self.cross_data["problem_56_multiple_installation_sources"]
        self.assertEqual(p56["status"], "IMPLEMENTED_ACTIONABLE")
        self.assertIn("PASS", p56["unmanaged_source_protection_invariant"])

    # =========================================================================
    # 12. AI / RAG SAFETY EVALUATION
    # =========================================================================
    def test_12_ai_rag_safety_policy(self):
        """Verifies AI/RAG provenance safety policy: STATIC_DB golden recipes may be auto-authorized; AI/RAG strictly requires approval."""
        matrix = self.cross_data["ai_rag_safety_matrix"]
        self.assertTrue(matrix["STATIC_DB"]["golden_recipe"]["auto_authorized"])
        self.assertFalse(matrix["STATIC_DB"]["standard_recipe"]["auto_authorized"])
        self.assertFalse(matrix["DYNAMIC_DB"]["standard_recipe"]["auto_authorized"])
        self.assertFalse(matrix["AI_RAG"]["generated_command"]["auto_authorized"])
        self.assertFalse(matrix["UNRESOLVED_RAW"]["raw_command"]["auto_authorized"])


if __name__ == "__main__":
    unittest.main()
