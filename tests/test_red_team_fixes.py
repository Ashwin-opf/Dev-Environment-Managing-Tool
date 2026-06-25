"""
Unit tests for Red-Team audit fixes.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.append(str(backend_dir))

from safety import SafetyLayer, extract_subshells, is_blocked_script_execution

class TestRedTeamFixes(unittest.TestCase):
    def setUp(self):
        import feature_flags
        feature_flags.ENABLE_DEV_MODE = False
        self.safety = SafetyLayer()

    def test_extract_subshells(self):
        cmd = "echo $(rm -rf /) $(ls)"
        self.assertEqual(extract_subshells(cmd), ["rm -rf /", "ls"])

        cmd_backticks = "echo `rm -rf /` `ls`"
        self.assertEqual(extract_subshells(cmd_backticks), ["rm -rf /", "ls"])

    def test_subshell_bypass_blocked(self):
        # A command containing a nested dangerous command inside a subshell should be blocked
        blocked, reason = self.safety.validate("echo $(rm -rf /)", risk="High")
        self.assertTrue(blocked)
        self.assertIn("blocked subshell execution", reason.lower())

        blocked, reason = self.safety.validate("echo `rm -rf /`", risk="High")
        self.assertTrue(blocked)
        self.assertIn("blocked subshell execution", reason.lower())

    def test_blocked_script_execution(self):
        self.assertTrue(is_blocked_script_execution("./my_script.sh"))
        self.assertTrue(is_blocked_script_execution("../my_script.py"))
        self.assertTrue(is_blocked_script_execution("c:\\users\\test\\script.ps1"))
        self.assertTrue(is_blocked_script_execution("/home/user/malicious.sh"))
        self.assertFalse(is_blocked_script_execution("git"))
        self.assertFalse(is_blocked_script_execution("python3"))

    def test_local_script_execution_validation_blocked(self):
        blocked, reason = self.safety.validate("./my_script.sh", risk="High")
        self.assertTrue(blocked)
        self.assertIn("executing local scripts", reason.lower())

        blocked, reason = self.safety.validate("python3 /home/user/malicious.py", risk="High")
        self.assertTrue(blocked)
        self.assertIn("executing script file", reason.lower())

    def test_safe_write_path_blocks_shell_configs(self):
        from fastapi import HTTPException
        from routes_files import _safe_write_path
        
        # Mock Path.home() and _is_home_path
        with patch("pathlib.Path.home", return_value=Path("/home/user")):
            with patch("routes_files._is_home_path", return_value=True):
                # Try writing to ~/.bashrc
                with self.assertRaises(HTTPException) as ctx:
                    _safe_write_path("/home/user/.bashrc")
                self.assertEqual(ctx.exception.status_code, 403)
                self.assertIn("blocked", ctx.exception.detail.lower())

                # Try writing to ~/.ssh/authorized_keys
                with self.assertRaises(HTTPException) as ctx:
                    _safe_write_path("/home/user/.ssh/authorized_keys")
                self.assertEqual(ctx.exception.status_code, 403)
                self.assertIn("blocked", ctx.exception.detail.lower())

if __name__ == "__main__":
    unittest.main()
