"""
Unit and integration tests for DevTools update streaming and uninstallation endpoints.

Tests cover:
- get_managed_devtools() (listing managed apps)
- devtools_update_stream() (SSE event streaming with phase/pct validation)
- devtools_uninstall_app() (uninstallation with confirmation guard and removal from manager)
- Error paths: invalid app_id, unconfirmed uninstall, missing update command, 404s
"""
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add backend directory to Python path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi import HTTPException
from routes_system import (
    get_managed_devtools,
    devtools_update_stream,
    devtools_uninstall_app,
    UninstallRequest,
)
from devtools_manager import devtools_manager


class TestDevToolsEndpointsDirect(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Register a test app in devtools_manager
        self.test_app_id = "test-stream-tool"
        devtools_manager.install_tool({
            "name": "Test Stream Tool",
            "app_id": self.test_app_id,
            "install_command": "echo install",
            "update_command": "echo updating-stream",
            "uninstall_command": "echo uninstalling-stream",
            "category": "Testing",
            "description": "A tool used for testing SSE update streaming."
        })

    def tearDown(self):
        devtools_manager.remove_managed_app(self.test_app_id)
        devtools_manager.remove_managed_app("sample-uninstall-tool")

    async def test_get_managed_devtools(self):
        result = await get_managed_devtools()
        self.assertTrue(result.get("ok"))
        apps = result.get("apps", [])
        self.assertTrue(any(a["app_id"] == self.test_app_id for a in apps))

    async def test_update_stream_missing_app_id(self):
        with self.assertRaises(HTTPException) as ctx:
            await devtools_update_stream(app_id="")
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_update_stream_nonexistent_app(self):
        with self.assertRaises(HTTPException) as ctx:
            await devtools_update_stream(app_id="nonexistent-app-xyz")
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_update_stream_success_flow(self):
        response = await devtools_update_stream(app_id=self.test_app_id)
        self.assertEqual(response.media_type, "text/event-stream")
        self.assertEqual(response.headers["Cache-Control"], "no-cache")

        # Iterate through the async generator body
        events = []
        async for chunk in response.body_iterator:
            for line in chunk.strip().split("\n"):
                if line.startswith("data: "):
                    raw_json = line[6:]
                    try:
                        events.append(json.loads(raw_json))
                    except Exception:
                        pass

        self.assertTrue(len(events) > 0)
        phases = [e.get("phase") for e in events]
        self.assertIn("fetching", phases)
        self.assertIn("done", phases)

        # Check the done event has pct=100 and ok=True
        done_event = next(e for e in events if e.get("phase") == "done")
        self.assertEqual(done_event.get("pct"), 100)
        self.assertTrue(done_event.get("ok"))

    async def test_uninstall_missing_app_id(self):
        req = UninstallRequest(app_id="", confirm=True)
        with self.assertRaises(HTTPException) as ctx:
            await devtools_uninstall_app(req)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_uninstall_unconfirmed(self):
        req = UninstallRequest(app_id=self.test_app_id, confirm=False)
        with self.assertRaises(HTTPException) as ctx:
            await devtools_uninstall_app(req)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_uninstall_nonexistent_app(self):
        req = UninstallRequest(app_id="nonexistent-app-xyz", confirm=True)
        with self.assertRaises(HTTPException) as ctx:
            await devtools_uninstall_app(req)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_uninstall_success(self):
        # Register a tool specifically for uninstall
        devtools_manager.install_tool({
            "name": "Sample Uninstall Tool",
            "app_id": "sample-uninstall-tool",
            "install_command": "echo install",
            "update_command": "echo update",
            "uninstall_command": "echo uninstalled",
        })

        req = UninstallRequest(app_id="sample-uninstall-tool", confirm=True)
        res = await devtools_uninstall_app(req)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("app_id"), "sample-uninstall-tool")

        # Verify app is removed from manager
        self.assertIsNone(devtools_manager.get_managed_app("sample-uninstall-tool"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
