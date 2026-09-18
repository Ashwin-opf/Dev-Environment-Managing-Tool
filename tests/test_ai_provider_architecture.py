"""
tests/test_ai_provider_architecture.py — Architecture-Level Tests for AI Provider & Model Decoupling

Verifies the 10 Non-Negotiable Contract Requirements:
1. Select NVIDIA -> No unrelated hardcoded Llama 3.1 8B / Mixtral entries.
2. Select OpenAI -> Only OpenAI-compatible models.
3. Select Google -> Only Google-compatible models.
4. Select xAI -> Only xAI-compatible models.
5. Select Ollama -> Actual locally available Ollama models only.
6. Change NVIDIA -> Google -> Provider catalogs are completely decoupled.
7. Change Google -> NVIDIA -> Provider catalogs are completely decoupled.
8. NVIDIA model discovery failure -> Shows discovery error / retry, DO NOT show unrelated hardcoded models.
9. Invalid provider/model combination -> Backend rejects it with HTTP 400.
10. Existing saved configuration using an unavailable model -> Marked NEEDS_RECONFIGURATION, not silently replaced.
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add backend to sys.path
backend_dir = Path(__file__).parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from ai_providers import (
    AI_PROVIDERS,
    BaseAIProvider,
    GoogleProvider,
    NVIDIAProvider,
    OllamaProvider,
    OpenAIProvider,
    XAIProvider,
    get_provider_adapter,
)
from routes_ai_config import (
    ProviderConfigBody,
    TestProviderBody,
    get_ai_models,
    get_providers,
    save_provider_config,
    test_provider,
)
from fastapi import HTTPException


class TestAIProviderArchitecture(unittest.TestCase):
    """Verifies complete decoupling of Providers and Models."""

    def setUp(self):
        self.nvidia_adapter = get_provider_adapter("nvidia")
        self.openai_adapter = get_provider_adapter("openai")
        self.gemini_adapter = get_provider_adapter("gemini")
        self.xai_adapter = get_provider_adapter("xai")
        self.ollama_adapter = get_provider_adapter("ollama")

    def test_1_nvidia_no_hardcoded_llama_or_mixtral(self):
        """TEST 1: Select NVIDIA -> No unrelated hardcoded Llama 3.1 8B / Mixtral entries."""
        res = self.nvidia_adapter.get_models()
        model_ids = [m["model_id"] for m in res["models"]]

        # Absolutely MUST NOT contain the deprecated hardcoded mappings
        self.assertNotIn("meta/llama-3.1-8b-instruct", model_ids)
        self.assertNotIn("mistralai/mixtral-8x7b-instruct-v0.1", model_ids)

        # All returned models must belong to NVIDIA's NIM namespace or verified NIM catalog
        for m in res["models"]:
            self.assertEqual(m["provider_id"], "nvidia")
            self.assertTrue(
                m["model_id"].startswith("nvidia/") or m["model_id"].startswith("meta/") or m["model_id"].startswith("deepseek-ai/"),
                f"Model {m['model_id']} has unexpected namespace for NVIDIA",
            )

    def test_2_openai_only_openai_compatible_models(self):
        """TEST 2: Select OpenAI -> Only OpenAI-compatible models."""
        res = self.openai_adapter.get_models()
        self.assertTrue(len(res["models"]) > 0)
        for m in res["models"]:
            self.assertEqual(m["provider_id"], "openai")
            self.assertTrue(
                m["model_id"].startswith("gpt-") or m["model_id"].startswith("o1-") or m["model_id"].startswith("o3-"),
                f"Non-OpenAI model found in OpenAI catalog: {m['model_id']}",
            )
            valid, _ = self.openai_adapter.validate_model(m["model_id"])
            self.assertTrue(valid)

        # Incompatible models must be rejected
        self.assertFalse(self.openai_adapter.validate_model("gemini-2.0-flash")[0])
        self.assertFalse(self.openai_adapter.validate_model("nvidia/nemotron-4-340b-instruct")[0])
        self.assertFalse(self.openai_adapter.validate_model("grok-2-1212")[0])

    def test_3_google_only_google_compatible_models(self):
        """TEST 3: Select Google -> Only Google-compatible models."""
        res = self.gemini_adapter.get_models()
        self.assertTrue(len(res["models"]) > 0)
        for m in res["models"]:
            self.assertEqual(m["provider_id"], "gemini")
            self.assertIn("gemini", m["model_id"].lower())
            valid, _ = self.gemini_adapter.validate_model(m["model_id"])
            self.assertTrue(valid)

        # Incompatible models must be rejected
        self.assertFalse(self.gemini_adapter.validate_model("gpt-4o")[0])
        self.assertFalse(self.gemini_adapter.validate_model("nvidia/llama-3.1-nemotron-70b-instruct")[0])

    def test_4_xai_only_xai_compatible_models(self):
        """TEST 4: Select xAI -> Only xAI-compatible models."""
        res = self.xai_adapter.get_models()
        self.assertTrue(len(res["models"]) > 0)
        for m in res["models"]:
            self.assertEqual(m["provider_id"], "xai")
            self.assertIn("grok", m["model_id"].lower())
            valid, _ = self.xai_adapter.validate_model(m["model_id"])
            self.assertTrue(valid)

        # Incompatible models must be rejected
        self.assertFalse(self.xai_adapter.validate_model("gpt-4o")[0])
        self.assertFalse(self.xai_adapter.validate_model("gemini-1.5-flash")[0])

    def test_5_ollama_local_models_only_no_cloud_mixing(self):
        """TEST 5: Select Ollama -> Actual locally available Ollama models only."""
        fake_local = ["deepseek-r1:8b", "qwen2.5-coder:7b"]
        with patch("routes_ai_config._requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"models": [{"name": m} for m in fake_local]}
            mock_get.return_value = mock_resp

            res = self.ollama_adapter.get_models()
            self.assertEqual(res["status"], "DISCOVERED")
            discovered_ids = [m["model_id"] for m in res["models"]]
            self.assertEqual(discovered_ids, fake_local)

            # Never mixes cloud models
            self.assertNotIn("gpt-4o", discovered_ids)
            self.assertNotIn("gemini-2.0-flash", discovered_ids)

    def test_6_and_7_provider_catalogs_are_completely_decoupled(self):
        """TEST 6 & 7: Changing provider replaces catalog completely without model leakage."""
        nvidia_models = set(m["model_id"] for m in self.nvidia_adapter.get_models()["models"])
        gemini_models = set(m["model_id"] for m in self.gemini_adapter.get_models()["models"])
        openai_models = set(m["model_id"] for m in self.openai_adapter.get_models()["models"])

        # Disjoint sets: No model crosses provider boundaries
        self.assertTrue(nvidia_models.isdisjoint(gemini_models))
        self.assertTrue(nvidia_models.isdisjoint(openai_models))
        self.assertTrue(gemini_models.isdisjoint(openai_models))

    def test_8_nvidia_discovery_failure_shows_error_no_hardcoded_fallback(self):
        """TEST 8: NVIDIA model discovery failure -> Returns error/retry, NEVER hardcoded fallback models."""
        with patch("ai_providers._requests.get") as mock_get:
            # Simulate 401 Invalid Key
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_get.return_value = mock_resp

            res = self.nvidia_adapter.get_models(api_key="nvapi-invalid-key-test")
            self.assertEqual(res["status"], "MODEL_DISCOVERY_FAILED")
            self.assertEqual(len(res["models"]), 0)
            self.assertIn("Invalid API key", res["error"])
            # Must NOT fallback to Llama 3.1 8B or Mixtral
            self.assertNotIn("meta/llama-3.1-8b-instruct", [m.get("model_id") for m in res.get("models", [])])

    def test_9_invalid_provider_model_combination_rejected_by_backend(self):
        """TEST 9: Invalid provider/model combination -> Backend rejects with HTTP 400."""
        # 1. Attempting to assign OpenAI model (gpt-4o) to NVIDIA
        body_inv_nvidia = ProviderConfigBody(provider="nvidia", model="gpt-4o")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(save_provider_config(body_inv_nvidia))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not compatible", ctx.exception.detail)

        # 2. Attempting to assign Google model to OpenAI
        body_inv_openai = ProviderConfigBody(provider="openai", model="gemini-1.5-flash")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(save_provider_config(body_inv_openai))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not compatible", ctx.exception.detail)

        # 3. Valid combination accepted
        body_valid_nvidia = ProviderConfigBody(provider="nvidia", model="nvidia/llama-3.1-nemotron-70b-instruct")
        with patch("routes_ai_config._save_config") as mock_save:
            res = asyncio.run(save_provider_config(body_valid_nvidia))
            self.assertTrue(res["ok"])
            self.assertEqual(res["model"], "nvidia/llama-3.1-nemotron-70b-instruct")

    def test_10_saved_configuration_with_unavailable_model_marked_needs_reconfiguration(self):
        """TEST 10: Existing saved configuration using an unavailable model -> marked NEEDS_RECONFIGURATION."""
        fake_cfg = {
            "active_provider": "nvidia",
            "provider_settings": {
                "nvidia": {
                    "model": "outdated-or-invalid-model-id"
                }
            }
        }
        with patch("routes_ai_config._load_config", return_value=fake_cfg):
            res = asyncio.run(get_ai_models(provider="nvidia"))
            self.assertTrue(res["ok"])
            self.assertFalse(res["is_model_valid"])
            self.assertEqual(res["model_status"], "NEEDS_RECONFIGURATION")
            self.assertEqual(res["active_model"], "outdated-or-invalid-model-id")


if __name__ == "__main__":
    unittest.main()
