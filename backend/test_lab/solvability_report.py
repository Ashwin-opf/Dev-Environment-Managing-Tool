"""
test_lab/solvability_report.py — Test lab solvability and coverage metrics aggregator.

Produces structured and markdown reports measuring:
- Detection rate
- Diagnosis rate
- Recipe resolution rate
- Safety pass rate
- Repair rate
- Independent verification rate (L1, L2, L3, L5)
- Baseline restoration rate
- Expected review-only cases
- Correctly blocked cases
- Solvability coverage across tested capabilities
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from test_lab.models import TestResult, TestStatus

logger = logging.getLogger("pc_doctor.test_lab.solvability_report")


class SolvabilityReporter:
    """
    Aggregates test results across runs and generates structured solvability metrics.
    """

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or (Path(__file__).parent.parent / "test_lab_results.json")
        self._results: List[TestResult] = []
        self._load()

    def record_result(self, result: TestResult) -> None:
        """Add a test result and persist to history."""
        self._results.append(result)
        self._save()

    def get_history(self) -> List[TestResult]:
        """Return all recorded test results."""
        return list(self._results)

    def clear_history(self) -> None:
        """Clear recorded test results history."""
        self._results.clear()
        self._save()

    def generate_report(self, results: Optional[List[TestResult]] = None) -> Dict[str, Any]:
        """
        Compute aggregate solvability and test health metrics.
        """
        targets = results if results is not None else self._results
        total = len(targets)

        if total == 0:
            return {
                "tests_executed": 0,
                "detection": {"passed": 0, "total": 0, "rate": 0.0},
                "diagnosis": {"passed": 0, "total": 0, "rate": 0.0},
                "recipe_resolution": {"passed": 0, "total": 0, "rate": 0.0},
                "safety": {"passed": 0, "total": 0, "rate": 0.0},
                "repair": {"passed": 0, "total": 0, "rate": 0.0},
                "verification": {"passed": 0, "total": 0, "rate": 0.0},
                "restoration": {"passed": 0, "total": 0, "rate": 0.0},
                "expected_review_only": 0,
                "blocked_correctly": 0,
                "failed_restoration": 0,
                "testable_capabilities": [],
                "tested_fault_ids": [],
                "overall_success_rate": 0.0,
                "markdown_summary": "No test runs executed yet.",
                "disclaimer": "This report measures tested cases only. It does not imply all catalog problems are solved.",
            }

        det_passed = sum(1 for r in targets if r.detected)
        diag_passed = sum(1 for r in targets if r.diagnosed)
        recipe_passed = sum(1 for r in targets if r.recipe_resolved)
        safety_passed = sum(1 for r in targets if r.safety_passed)
        repair_passed = sum(1 for r in targets if r.repair_executed)
        verif_passed = sum(1 for r in targets if r.repair_verified)
        
        # Restoration is relevant whenever a baseline was captured and restoration was attempted
        restoration_applicable = [r for r in targets if r.baseline_captured]
        rest_total = len(restoration_applicable)
        rest_passed = sum(1 for r in restoration_applicable if r.baseline_restored and r.restoration_verified)

        expected_review = sum(1 for r in targets if r.result == TestStatus.PASS_EXPECTED_REVIEW)
        blocked_correctly = sum(1 for r in targets if r.result in (TestStatus.BLOCKED_EXPECTED, TestStatus.SIMULATION_ONLY))
        failed_restoration = sum(1 for r in targets if r.result == TestStatus.FAILED_RESTORATION)

        overall_passed = sum(
            1 for r in targets
            if r.result in (TestStatus.PASS, TestStatus.PASS_EXPECTED_REVIEW, TestStatus.BLOCKED_EXPECTED, TestStatus.SIMULATION_ONLY)
        )

        capabilities = sorted(list({r.fault_id.split("_")[0] for r in targets if r.fault_id}))
        fault_ids = sorted(list({r.fault_id for r in targets if r.fault_id}))

        def calc_rate(passed: int, denom: int) -> float:
            return round((passed / denom) * 100.0, 1) if denom > 0 else 0.0

        markdown = self._generate_markdown(
            total=total,
            det_passed=det_passed,
            diag_passed=diag_passed,
            recipe_passed=recipe_passed,
            safety_passed=safety_passed,
            repair_passed=repair_passed,
            verif_passed=verif_passed,
            rest_passed=rest_passed,
            rest_total=rest_total,
            expected_review=expected_review,
            blocked_correctly=blocked_correctly,
            overall_passed=overall_passed,
            failed_restoration=failed_restoration,
            fault_ids=fault_ids,
        )

        return {
            "tests_executed": total,
            "detection": {"passed": det_passed, "total": total, "rate": calc_rate(det_passed, total)},
            "diagnosis": {"passed": diag_passed, "total": total, "rate": calc_rate(diag_passed, total)},
            "recipe_resolution": {"passed": recipe_passed, "total": total, "rate": calc_rate(recipe_passed, total)},
            "safety": {"passed": safety_passed, "total": total, "rate": calc_rate(safety_passed, total)},
            "repair": {"passed": repair_passed, "total": total, "rate": calc_rate(repair_passed, total)},
            "verification": {"passed": verif_passed, "total": total, "rate": calc_rate(verif_passed, total)},
            "restoration": {"passed": rest_passed, "total": rest_total, "rate": calc_rate(rest_passed, rest_total)},
            "expected_review_only": expected_review,
            "blocked_correctly": blocked_correctly,
            "failed_restoration": failed_restoration,
            "overall_success_rate": calc_rate(overall_passed, total),
            "testable_capabilities": capabilities,
            "tested_fault_ids": fault_ids,
            "history": [r.to_dict() for r in targets],
            "markdown_summary": markdown,
            "disclaimer": "This report measures tested cases only. Solvability is verified only for problem cases with an implemented detector + diagnosis + recipe + safety + verification path.",
        }

    def _generate_markdown(
        self,
        total: int,
        det_passed: int,
        diag_passed: int,
        recipe_passed: int,
        safety_passed: int,
        repair_passed: int,
        verif_passed: int,
        rest_passed: int,
        rest_total: int,
        expected_review: int,
        blocked_correctly: int,
        overall_passed: int,
        failed_restoration: int,
        fault_ids: List[str],
    ) -> str:
        lines = [
            "## PC Doctor Fault Injection Report",
            f"**Tests executed:** {total}",
            "",
            "### Pipeline Metrics",
            f"- **Detection:** {det_passed}/{total} ({round((det_passed/total)*100, 1) if total else 0}%)",
            f"- **Diagnosis:** {diag_passed}/{total} ({round((diag_passed/total)*100, 1) if total else 0}%)",
            f"- **Recipe resolution:** {recipe_passed}/{total} ({round((recipe_passed/total)*100, 1) if total else 0}%)",
            f"- **Safety:** {safety_passed}/{total} ({round((safety_passed/total)*100, 1) if total else 0}%)",
            f"- **Repair:** {repair_passed}/{total} ({round((repair_passed/total)*100, 1) if total else 0}%)",
            f"- **Verification:** {verif_passed}/{total} ({round((verif_passed/total)*100, 1) if total else 0}%)",
            f"- **Restoration:** {rest_passed}/{rest_total} ({round((rest_passed/rest_total)*100, 1) if rest_total else 100}%)",
            "",
            "### Policy Outcomes",
            f"- **Expected review-only:** {expected_review}",
            f"- **Blocked correctly:** {blocked_correctly}",
            f"- **Failed restorations:** {failed_restoration}",
            f"- **Overall test pass rate:** {overall_passed}/{total} ({round((overall_passed/total)*100, 1) if total else 0}%)",
            "",
            f"**Tested Fault Scenarios:** {', '.join(fault_ids) if fault_ids else 'None'}",
            "",
            "> [!NOTE]",
            "> This report measures tested cases only. Solvability is verified only for problem cases with an implemented detector + diagnosis + recipe + safety + verification path.",
        ]
        return "\n".join(lines)

    def _save(self) -> None:
        try:
            raw = [r.to_dict() for r in self._results]
            self.storage_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to save test lab results: %s", e)

    def _load(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            content = self.storage_path.read_text(encoding="utf-8")
            raw = json.loads(content)
            self._results = []
            for item in raw:
                try:
                    res_dict = dict(item)
                    if "result" in res_dict and isinstance(res_dict["result"], str):
                        res_dict["result"] = TestStatus(res_dict["result"])
                    self._results.append(TestResult(**res_dict))
                except Exception as inner_e:
                    logger.warning("Failed to deserialize test result record: %s", inner_e)
        except Exception as e:
            logger.error("Failed to load test lab results: %s", e)


# Global singleton instance
solvability_reporter = SolvabilityReporter()
