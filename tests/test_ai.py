"""
Tests for PC Doctor AI Assistant module.
"""
import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.append(str(backend_dir))

import ai_assistant

class TestAIAssistant(unittest.TestCase):

    @patch("ai_assistant.os.getenv")
    @patch("ai_assistant.shutil.which")
    def test_ollama_not_available(self, mock_which, mock_getenv):
        # Simulate Ollama not installed and no HTTP service configured
        mock_which.return_value = None
        mock_getenv.return_value = ""
        self.assertFalse(ai_assistant.ollama_available())
        
        response = ai_assistant.ask_ollama("hello")
        self.assertIn("Ollama is not installed", response)

    @patch("ai_assistant.ollama_service_url")
    @patch("ai_assistant.list_local_models")
    @patch("ai_assistant.shutil.which")
    @patch("ai_assistant.subprocess.run")
    def test_ollama_available_success(self, mock_run, mock_which, mock_list_local, mock_service_url):
        # Simulate Ollama installed and running successfully
        mock_which.return_value = "/usr/local/bin/ollama"
        mock_service_url.return_value = None
        mock_list_local.return_value = ["phi"]
        
        mock_process = MagicMock()
        mock_process.return_value.returncode = 0
        mock_process.return_value.stdout = b"Hello, I am PC Doctor."
        mock_run.return_value = mock_process.return_value

        response = ai_assistant.ask_ollama("hello", model="phi")
        self.assertEqual(response, "Hello, I am PC Doctor.")
        
        # Verify it was called with correct args
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertEqual(args, ["ollama", "run", "phi"])

    @patch("ai_assistant.list_local_models")
    @patch("ai_assistant.os.getenv")
    @patch("ai_assistant.requests.post")
    def test_ollama_http_service(self, mock_post, mock_getenv, mock_list_local):
        # Simulate Ollama HTTP service configured and responding successfully
        mock_getenv.return_value = "http://ollama:11434"
        mock_list_local.return_value = ["phi"]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "Hello from Ollama."}}]
        }
        mock_post.return_value = mock_response

        response = ai_assistant.ask_ollama("hello", model="phi")
        self.assertEqual(response, "Hello from Ollama.")
        mock_post.assert_called_once()

    @patch("ai_assistant.ollama_service_url")
    @patch("ai_assistant.list_local_models")
    @patch("ai_assistant.shutil.which")
    @patch("ai_assistant.subprocess.run")
    def test_ollama_error_status(self, mock_run, mock_which, mock_list_local, mock_service_url):
        # Simulate Ollama returns an error code
        mock_which.return_value = "/usr/local/bin/ollama"
        mock_service_url.return_value = None
        mock_list_local.return_value = ["non-existent"]
        
        mock_process = MagicMock()
        mock_process.return_value.returncode = 1
        mock_process.return_value.stderr = b"Model not found"
        mock_run.return_value = mock_process.return_value

        response = ai_assistant.ask_ollama("hello", model="non-existent")
        self.assertIn("Ollama error: Model not found", response)

if __name__ == "__main__":
    unittest.main()
