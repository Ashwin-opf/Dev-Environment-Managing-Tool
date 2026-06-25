"""
Unit tests for the Temporary Development Mode Refactor.
"""
import sys
import unittest
import sqlite3
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.append(str(backend_dir))

import dev_sandbox
from safety import SafetyLayer
from self_healing import DB_PATH

class TestDevelopmentMode(unittest.TestCase):
    def setUp(self):
        self.safety = SafetyLayer()

    def test_development_mode_bypass_and_logging(self):
        # 1. Test when ENABLE_DEV_MODE is True
        # Mock feature flags ENABLE_DEV_MODE to True
        import feature_flags
        original_mode = feature_flags.ENABLE_DEV_MODE
        feature_flags.ENABLE_DEV_MODE = True

        # Run validate on a dangerous block command
        cmd = "rm -rf /"
        blocked, reason = self.safety.validate(cmd, risk="High")
        
        # In DEV MODE, it should NOT block, but return a WARNING
        self.assertFalse(blocked)
        self.assertTrue(reason.startswith("WARNING:"))

        # Check SQLite db for logged override
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT action, original_safety_result, override_reason FROM safety_overrides ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        action, orig_result, override_reason = row
        self.assertEqual(action, cmd)
        self.assertIn("Blocked", orig_result)
        self.assertEqual(override_reason, "DEVELOPMENT_MODE Safety Bypass")

        # 2. Test when ENABLE_DEV_MODE is False
        feature_flags.ENABLE_DEV_MODE = False
        blocked, reason = self.safety.validate(cmd, risk="High")
        
        # It should block as normal
        self.assertTrue(blocked)
        self.assertIn("matches dangerous pattern", reason)

        # Restore original value
        feature_flags.ENABLE_DEV_MODE = original_mode

    def test_dev_sandbox_features(self):
        # Test test_orchestrator
        orch_res = dev_sandbox.test_orchestrator("restart docker")
        self.assertEqual(orch_res["status"], "success")
        self.assertEqual(orch_res["action"], "restart docker")
        self.assertEqual(orch_res["mode"], "sandbox")
        self.assertTrue(len(orch_res["steps_executed"]) > 0)

        # Test test_repair_plan
        plan = {"id": "plan-xyz", "steps": ["step 1", "step 2"]}
        plan_res = dev_sandbox.test_repair_plan(plan)
        self.assertEqual(plan_res["status"], "success")
        self.assertEqual(plan_res["plan_id"], "plan-xyz")
        self.assertEqual(plan_res["steps_count"], 2)

        # Test test_rag_retrieval
        rag_res = dev_sandbox.test_rag_retrieval("missing tools")
        self.assertEqual(rag_res["query"], "missing tools")
        self.assertTrue(len(rag_res["results"]) > 0)

        # Test test_adaptive_workflow
        flow_res = dev_sandbox.test_adaptive_workflow("auto-patch")
        self.assertEqual(flow_res["workflow"], "auto-patch")
        self.assertEqual(flow_res["status"], "completed")
        self.assertEqual(flow_res["confidence_score"], 0.95)

if __name__ == "__main__":
    unittest.main()
