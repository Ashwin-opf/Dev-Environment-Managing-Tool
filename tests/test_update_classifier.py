"""
test_update_classifier.py — Verifies result classification and capability resolution for updates.
"""
import sys
import unittest
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from result_classifier import classify_execution_result, get_publisher_managed_info
from routes_system import resolve_app_action_spec


class TestUpdateClassifier(unittest.TestCase):

    def test_publisher_managed_winget_output(self):
        """WinGet publisher-managed message is classified as UPDATE_UNSUPPORTED_BY_PACKAGE_MANAGER."""
        winget_out = (
            "Found Anaconda3 [Anaconda.Anaconda3] Version 2024.10-1\n"
            "This application is licensed to you by its publisher.\n"
            "Microsoft is not responsible for, nor does it grant any licenses to, third-party packages.\n"
            "The package cannot be upgraded using WinGet.\n"
            "Please use the method provided by the publisher for upgrading this package.\n"
        )
        res = classify_execution_result(
            command='winget upgrade --id "Anaconda.Anaconda3" --exact --silent',
            returncode=1,
            stdout=winget_out,
            stderr="",
            operation="UPDATE",
            app_name="Anaconda3 2024.10-1 (Python 3.12.7 64-bit)",
            package_id="Anaconda.Anaconda3",
        )
        self.assertEqual(res["classification"], "UPDATE_UNSUPPORTED_BY_PACKAGE_MANAGER")
        self.assertFalse(res["is_success"])
        self.assertTrue(res["is_publisher_managed"])
        self.assertIn("cannot be upgraded using WinGet", res["explanation"])
        self.assertFalse(res["retry_supported"])
        self.assertIn("anaconda.com", res.get("official_url", "").lower())

    def test_eight_classification_outcomes(self):
        """Validates all 8 required outcome states."""
        # 1. SUCCESS
        r1 = classify_execution_result("winget upgrade --id Git.Git", 0, "Successfully installed", "")
        self.assertEqual(r1["classification"], "SUCCESS")
        self.assertTrue(r1["is_success"])

        # 2. UPDATE_NOT_AVAILABLE
        r2 = classify_execution_result("winget upgrade --id Git.Git", 0, "No applicable update found", "")
        self.assertEqual(r2["classification"], "UPDATE_NOT_AVAILABLE")

        # 3. UPDATE_UNSUPPORTED_BY_PACKAGE_MANAGER
        r3 = classify_execution_result(
            "winget upgrade --id Anaconda.Anaconda3", 1,
            "The package cannot be upgraded using WinGet. Please use the method provided by the publisher.", ""
        )
        self.assertEqual(r3["classification"], "UPDATE_UNSUPPORTED_BY_PACKAGE_MANAGER")

        # 4. PACKAGE_NOT_FOUND
        r4 = classify_execution_result("winget upgrade --id Fake.App", 1, "No installed package found matching input criteria.", "")
        self.assertEqual(r4["classification"], "PACKAGE_NOT_FOUND")

        # 5. PERMISSION_DENIED
        r5 = classify_execution_result("winget install --id Test", 5, "Access is denied. Administrator privileges required.", "")
        self.assertEqual(r5["classification"], "PERMISSION_DENIED")

        # 6. NETWORK_ERROR
        r6 = classify_execution_result("winget upgrade --all", 1, "Failed to connect: 0x80072ee7", "")
        self.assertEqual(r6["classification"], "NETWORK_ERROR")

        # 7. VERIFICATION_FAILED
        r7 = classify_execution_result("winget install --id Test", 1, "Installer hash does not match; checksum mismatch", "")
        self.assertEqual(r7["classification"], "VERIFICATION_FAILED")

        # 8. COMMAND_EXECUTION_FAILED
        r8 = classify_execution_result("some_bad_cmd", 127, "", "command not found")
        self.assertEqual(r8["classification"], "COMMAND_EXECUTION_FAILED")

    def test_anaconda_action_spec_capabilities(self):
        """Anaconda action spec reports update_supported=False and provides publisher instructions."""
        spec = resolve_app_action_spec("Anaconda3", "Anaconda.Anaconda3")
        self.assertTrue(spec["ok"])
        self.assertEqual(spec["package_id"], "Anaconda.Anaconda3")

        # Capability check
        self.assertFalse(spec["capabilities"]["update_supported"])
        self.assertTrue(spec["capabilities"]["install_supported"])

        # Update action
        upd = spec["update"]
        self.assertFalse(upd["supported"])
        self.assertEqual(upd["method"], "PUBLISHER_RECIPE")
        self.assertEqual(upd["publisher_command"], "conda update --all -y")
        self.assertIn("anaconda.com", upd["official_url"])
        self.assertIn("cannot be upgraded using WinGet", upd["instructions"])

        # Ensure update_command is NOT blind winget upgrade
        self.assertNotIn("|| winget upgrade --name", spec["update_command"])
        self.assertEqual(spec["update_command"], "conda update --all -y")


if __name__ == "__main__":
    unittest.main()
