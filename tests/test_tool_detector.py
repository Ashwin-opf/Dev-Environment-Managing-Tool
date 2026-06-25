import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from tool_detector import detect_tool, vscode_installed  # noqa: E402


class TestToolDetector(unittest.TestCase):
    def test_detect_tool_from_path(self):
        with patch("tool_detector._exists", return_value=True):
            self.assertTrue(detect_tool(paths=("/opt/example/bin",)))

    def test_detect_tool_false_when_nothing_matches(self):
        with patch("tool_detector._which", return_value=False), \
             patch("tool_detector._any_exists", return_value=False), \
             patch("tool_detector._flatpak_installed", return_value=False), \
             patch("tool_detector._snap_installed", return_value=False), \
             patch("tool_detector._desktop_installed", return_value=False), \
             patch("tool_detector._process_markers", return_value=False):
            self.assertFalse(detect_tool(binaries=("missing-tool",)))

    def test_vscode_flatpak_detection(self):
        with patch("tool_detector._which", return_value=False), \
             patch("tool_detector._any_exists", return_value=False), \
             patch("tool_detector._flatpak_installed", return_value=True):
            self.assertTrue(vscode_installed())


if __name__ == "__main__":
    unittest.main()
