import sys
import unittest
from pathlib import Path
import os
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

# Set temporary environment variable
os.environ["PC_DOCTOR_API_TOKEN"] = "test-secret-token"

from main import check_api_token


class TestAuthMiddlewareDirect(unittest.TestCase):
    @patch("main.API_TOKEN", "test-secret-token")
    def test_non_api_route_bypasses(self):
        import asyncio
        request = MagicMock()
        request.url.path = "/health"
        
        call_next = AsyncMock(return_value="OK")
        
        result = asyncio.run(check_api_token(request, call_next))
        self.assertEqual(result, "OK")
        call_next.assert_called_once_with(request)

    @patch("main.API_TOKEN", "test-secret-token")
    def test_api_route_blocked_without_token(self):
        import asyncio
        request = MagicMock()
        request.url.path = "/api/sysinfo"
        request.headers = {}
        
        call_next = AsyncMock(return_value="OK")
        
        result = asyncio.run(check_api_token(request, call_next))
        self.assertEqual(result.status_code, 401)
        call_next.assert_not_called()

    @patch("main.API_TOKEN", "test-secret-token")
    def test_api_route_blocked_with_invalid_token(self):
        import asyncio
        request = MagicMock()
        request.url.path = "/api/sysinfo"
        request.headers = {"Authorization": "Bearer wrong-token"}
        
        call_next = AsyncMock(return_value="OK")
        
        result = asyncio.run(check_api_token(request, call_next))
        self.assertEqual(result.status_code, 401)
        call_next.assert_not_called()

    @patch("main.API_TOKEN", "test-secret-token")
    def test_api_route_allows_correct_token(self):
        import asyncio
        request = MagicMock()
        request.url.path = "/api/sysinfo"
        request.headers = {"Authorization": "Bearer test-secret-token"}
        
        call_next = AsyncMock(return_value="OK")
        
        result = asyncio.run(check_api_token(request, call_next))
        self.assertEqual(result, "OK")
        call_next.assert_called_once_with(request)


if __name__ == "__main__":
    unittest.main()
