"""
Tests for PC Doctor Repair Engine and Safety Layer.
"""
import sys
import unittest
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.append(str(backend_dir))

from safety import SafetyLayer
from repair_engine import RepairEngine

class TestSafetyLayer(unittest.TestCase):
    def setUp(self):
        import feature_flags
        self.original_dev_mode = feature_flags.ENABLE_DEV_MODE
        feature_flags.ENABLE_DEV_MODE = False
        
        # Mock platform.system to return "Linux" by default for safety tests to run consistently
        from unittest.mock import patch
        self.system_patcher = patch("platform.system", return_value="Linux")
        self.mock_system = self.system_patcher.start()
        
        self.safety = SafetyLayer()

    def tearDown(self):
        import feature_flags
        feature_flags.ENABLE_DEV_MODE = self.original_dev_mode
        self.system_patcher.stop()

    def test_blocked_commands(self):
        # Dangerous commands that must be blocked regardless of risk level
        blocked_commands = [
            "rm -rf /",
            "rm -rf /*",
            "mkfs.ext4 /dev/sda1",
            "dd if=/dev/zero of=/dev/sda",
            "del /s /q C:\\Windows\\System32",
            "format C:",
            "reboot",
            "shutdown -h now",
        ]
        for cmd in blocked_commands:
            blocked, reason = self.safety.validate(cmd, risk="High")
            self.assertTrue(blocked, f"Should have blocked: {cmd}")
            self.assertIn("dangerous pattern", reason.lower())

    def test_high_risk_commands(self):
        # High-risk commands should be blocked if risk level is not 'High'
        high_risk = "sudo rm -rf /etc/test"
        
        # Blocked with low risk
        blocked, reason = self.safety.validate(high_risk, risk="Low")
        self.assertTrue(blocked)
        self.assertIn("high-risk", reason.lower())

        # Still blocked with high risk. The automated engine should not run
        # filesystem-destructive commands even when a caller labels them High.
        blocked, reason = self.safety.validate(high_risk, risk="High")
        self.assertTrue(blocked)
        self.assertIn("high-risk", reason.lower())

    def test_kernel_module_reload_blocked(self):
        blocked, reason = self.safety.validate("sudo modprobe -r nvme", risk="High")
        self.assertTrue(blocked)
        self.assertIn("dangerous pattern", reason.lower())

        blocked, reason = self.safety.validate("sudo modprobe i915", risk="High")
        self.assertTrue(blocked)
        self.assertIn("high-risk", reason.lower())

    def test_driver_package_update_allowed(self):
        command = (
            "sudo apt-get update && sudo apt-get install --only-upgrade -y "
            "linux-firmware linux-generic linux-generic-hwe-24.04"
        )
        from unittest.mock import patch
        with patch("safety._running_in_container", return_value=True):
            blocked, reason = self.safety.validate(command, risk="Medium")
            self.assertFalse(blocked, reason)

    def test_host_kernel_update_blocked_by_default(self):
        command = (
            "sudo apt-get update && sudo apt-get install --only-upgrade -y "
            "linux-firmware linux-generic linux-generic-hwe-24.04"
        )
        from unittest.mock import patch
        with patch("safety._running_in_container", return_value=False):
            blocked, reason = self.safety.validate(command, risk="Medium")
            self.assertTrue(blocked)
            self.assertIn("safe mode blocked", reason.lower())

    def test_system_update_allowed_with_action_key(self):
        command = "sudo apt update && sudo apt upgrade -y"
        from unittest.mock import patch
        with patch("safety._running_in_container", return_value=False):
            blocked, reason = self.safety.validate(command, risk="Medium", action_key="system_update")
            self.assertFalse(blocked, reason)

    def test_system_update_still_blocks_kernel_packages(self):
        command = (
            "sudo apt-get update && sudo apt-get install --only-upgrade -y "
            "linux-firmware linux-generic linux-generic-hwe-24.04"
        )
        from unittest.mock import patch
        with patch("safety._running_in_container", return_value=False):
            blocked, reason = self.safety.validate(command, risk="Medium", action_key="system_update")
            self.assertTrue(blocked)
            self.assertIn("safe mode blocked", reason.lower())

    def test_os_mismatch(self):
        # Windows command on Linux, or Linux command on Windows
        from unittest.mock import patch
        
        # Test Windows-only command on Linux (mocked platform = Linux)
        with patch("platform.system", return_value="Linux"):
            blocked, reason = self.safety.validate("winget install python", risk="Low")
            self.assertTrue(blocked)
            self.assertIn("windows-only", reason.lower())
            
        # Test Linux-only command on Windows (mocked platform = Windows)
        with patch("platform.system", return_value="Windows"):
            # Use a command that is Linux-only but not host-protected to avoid host-protection blocking it first
            blocked, reason = self.safety.validate("sudo apt install python", risk="Low")
            self.assertTrue(blocked)
            self.assertIn("linux-only", reason.lower())

    def test_empty_command(self):
        blocked, reason = self.safety.validate("   ", risk="Low")
        self.assertTrue(blocked)
        self.assertIn("empty", reason.lower())

    def test_unspaced_delimiters_split_and_block(self):
        # unspaced semicolon delimiter
        blocked, reason = self.safety.validate("rm -rf /;echo", risk="Low")
        self.assertTrue(blocked)
        self.assertIn("dangerous pattern", reason.lower())

        # unspaced && delimiter
        blocked, reason = self.safety.validate("echo hello&&rm -rf /", risk="Low")
        self.assertTrue(blocked)
        self.assertIn("dangerous pattern", reason.lower())

    def test_command_chain_bypass_with_action_key(self):
        # Chaining malicious command with approved command
        blocked, reason = self.safety.validate(
            "sudo apt update && sudo apt upgrade -y && rm -rf /",
            risk="Medium",
            action_key="system_update"
        )
        self.assertTrue(blocked)
        self.assertIn("dangerous pattern", reason.lower())

        # Chaining host-protected command with approved command
        from unittest.mock import patch
        with patch("safety._running_in_container", return_value=False):
            blocked, reason = self.safety.validate(
                "sudo apt update && sudo apt upgrade -y && sudo systemctl stop docker",
                risk="Medium",
                action_key="system_update"
            )
            self.assertTrue(blocked)
            self.assertIn("safe mode blocked", reason.lower())

    def test_backslashes_escaping_in_binary_names(self):
        # Escape obfuscation
        blocked, reason = self.safety.validate(r"sudo \rm -rf /", risk="Low")
        self.assertTrue(blocked)
        self.assertIn("dangerous pattern", reason.lower())

    def test_environment_variables_handling(self):
        # Prepended env vars should not obscure the binary name
        blocked, reason = self.safety.validate(
            "DEBIAN_FRONTEND=noninteractive sudo rm -rf /var",
            risk="Low"
        )
        self.assertTrue(blocked)
        self.assertIn("destructive directory removal", reason.lower())


class TestRepairEngine(unittest.TestCase):
    def setUp(self):
        self.db_path = backend_dir / "knowledge.db"
        self.engine = RepairEngine(self.db_path)

    def test_list_recipes(self):
        recipes = self.engine.list_recipes()
        self.assertIsInstance(recipes, list)
        if recipes:
            for recipe in recipes:
                self.assertIn("issue", recipe)
                self.assertIn("command", recipe)
                self.assertIn("risk", recipe)

    def test_run_command_success(self):
        # Run a simple safe command
        out, err, code = self.engine.run("echo 'hello'")
        self.assertEqual(code, 0)
        self.assertIn("hello", out)

    def test_sudo_pkexec_wrapping(self):
        from unittest.mock import patch
        import platform

        if platform.system() == "Linux":
            with patch("subprocess.run") as mock_run:
                from unittest.mock import MagicMock
                mock_proc = MagicMock()
                mock_proc.stdout = "mocked out"
                mock_proc.stderr = ""
                mock_proc.returncode = 0
                mock_run.return_value = mock_proc

                # Run a sudo command
                self.engine.run("sudo apt-get update")

                # Verify that it was wrapped with pkexec as a list
                mock_run.assert_called_once()
                called_cmd = mock_run.call_args[0][0]
                self.assertEqual(called_cmd[0], "pkexec")
                self.assertEqual(called_cmd[1], "bash")
                self.assertEqual(called_cmd[2], "-c")
                self.assertIn("apt-get update", called_cmd[3])
                self.assertNotIn("sudo", called_cmd[3])

    def test_sudo_windows_runas_wrapping(self):
        from unittest.mock import patch

        with patch("platform.system", return_value="Windows"):
            with patch.object(self.engine, "run_elevated_operation", return_value={"ok": True, "status": "EXECUTED", "message": "Success"}) as mock_elevated:
                # Run a sudo command
                stdout, stderr, rc = self.engine.run("sudo winget upgrade --all")

                # Verify that it routes to isolated elevated operation
                mock_elevated.assert_called_once()
                payload = mock_elevated.call_args[0][0]
                self.assertEqual(payload["operation"], "EXECUTE_COMMAND")
                self.assertIn("winget upgrade --all", payload["command"])
                self.assertEqual(rc, 0)

if __name__ == "__main__":
    unittest.main()
