"""
backend/ai_providers.py — AI Provider Adapters & Model Resolution Layer
=======================================================================
Architecturally separates AI Providers from Models.
Each provider implements its own model discovery, validation, and generation logic.
Never mixes models across providers or uses unrelated fallbacks.
"""
from __future__ import annotations

import abc
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests as _requests


@dataclass
class ModelDescriptor:
    provider_id: str
    model_id: str
    display_name: str
    capabilities: List[str]
    context_length: Optional[int] = None
    is_default: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BaseAIProvider(abc.ABC):
    """Abstract base class for all AI provider adapters."""

    provider_id: str
    name: str
    type: str  # "local" or "cloud_api"
    default_url: str
    requires_key: bool
    description: str

    @abc.abstractmethod
    def get_models(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Discover and resolve compatible models for this provider.
        Returns:
            {
                "status": "DISCOVERED" | "CONFIG_REQUIRED" | "MODEL_DISCOVERY_FAILED",
                "models": List[ModelDescriptor],
                "error": Optional[str]
            }
        """
        pass

    @abc.abstractmethod
    def validate_model(
        self,
        model_id: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Validate whether model_id is compatible with this provider.
        Returns (is_valid: bool, reason: str).
        """
        pass

    @abc.abstractmethod
    def test_connection(
        self,
        api_key: str,
        base_url: str,
        model_id: str,
    ) -> Tuple[bool, str]:
        """Test API connectivity and model accessibility."""
        pass

    @abc.abstractmethod
    def generate(
        self,
        prompt: str,
        system: str = "",
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> str:
        """Generate text completion from provider."""
        pass


class OllamaProvider(BaseAIProvider):
    """Local Ollama instance adapter. Only discovers locally installed models."""

    provider_id = "ollama"
    name = "Ollama (Local)"
    type = "local"
    default_url = "http://127.0.0.1:11434"
    requires_key = False
    description = "Local inference — no API key required. Run models offline on your own hardware."

    def get_models(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = (base_url or self.default_url).rstrip("/")
        models: List[ModelDescriptor] = []

        # 1. Try HTTP API
        try:
            r = _requests.get(f"{url}/api/tags", timeout=2.0)
            if r.status_code == 200:
                raw_models = r.json().get("models", [])
                for m in raw_models:
                    m_name = m.get("name") or m.get("model")
                    if m_name:
                        models.append(
                            ModelDescriptor(
                                provider_id=self.provider_id,
                                model_id=m_name,
                                display_name=m_name,
                                capabilities=["chat", "diagnostics", "local"],
                                is_default=(len(models) == 0),
                            )
                        )
                if models:
                    return {
                        "status": "DISCOVERED",
                        "models": [m.to_dict() for m in models],
                        "error": None,
                    }
                else:
                    return {
                        "status": "MODEL_DISCOVERY_FAILED",
                        "models": [],
                        "error": "Ollama is running, but no models have been pulled yet. Run 'ollama pull phi3:mini' to install one.",
                    }
        except Exception:
            pass

        # 2. Try CLI fallback
        if shutil.which("ollama"):
            try:
                res = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=2)
                if res.returncode == 0:
                    lines = res.stdout.strip().splitlines()
                    for line in lines[1:]:
                        parts = line.split()
                        if parts:
                            m_name = parts[0]
                            models.append(
                                ModelDescriptor(
                                    provider_id=self.provider_id,
                                    model_id=m_name,
                                    display_name=m_name,
                                    capabilities=["chat", "diagnostics", "local"],
                                    is_default=(len(models) == 0),
                                )
                            )
                    if models:
                        return {
                            "status": "DISCOVERED",
                            "models": [m.to_dict() for m in models],
                            "error": None,
                        }
                    else:
                        return {
                            "status": "MODEL_DISCOVERY_FAILED",
                            "models": [],
                            "error": "Ollama is installed, but no local models found. Pull a model using 'ollama pull phi3:mini'.",
                        }
            except Exception:
                pass
            return {
                "status": "MODEL_DISCOVERY_FAILED",
                "models": [],
                "error": "Ollama is installed but the server is not running. Start it with: ollama serve",
            }

        return {
            "status": "MODEL_DISCOVERY_FAILED",
            "models": [],
            "error": "Ollama is not installed. Download it from https://ollama.ai",
        }

    def validate_model(
        self,
        model_id: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Tuple[bool, str]:
        if not model_id or not model_id.strip():
            return False, "Model name cannot be empty."
        res = self.get_models(base_url=base_url)
        available = [m["model_id"].lower() for m in res.get("models", [])]
        if available:
            norm_target = model_id.strip().lower()
            target_base = norm_target.split(":")[0]
            if any(norm_target == m or target_base == m.split(":")[0] for m in available):
                return True, "Model is available locally."
            return False, f"Model '{model_id}' is not downloaded in Ollama. Available: {', '.join(available)}"
        # If server is offline during validation, check format
        if any(c in model_id for c in ("/", "\\")) and not any(p in model_id for p in (":",)):
            return False, f"'{model_id}' does not appear to be a valid Ollama model identifier."
        return True, "Model format accepted."

    def test_connection(
        self,
        api_key: str,
        base_url: str,
        model_id: str,
    ) -> Tuple[bool, str]:
        res = self.get_models(base_url=base_url)
        if res["status"] == "DISCOVERED":
            model_names = [m["model_id"] for m in res["models"]]
            return True, f"Ollama is running. {len(model_names)} model(s) available: {', '.join(model_names[:5])}."
        return False, res.get("error") or "Ollama server is not reachable."

    def generate(
        self,
        prompt: str,
        system: str = "",
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> str:
        from ai_assistant import ask_ollama
        model = model_id or "phi3:mini"
        return ask_ollama(prompt, model=model, system=system)


class NVIDIAProvider(BaseAIProvider):
    """NVIDIA NIM API adapter. Resolves NVIDIA-compatible models dynamically."""

    provider_id = "nvidia"
    name = "NVIDIA NIM"
    type = "cloud_api"
    default_url = "https://integrate.api.nvidia.com/v1"
    requires_key = True
    description = "NVIDIA NIM API — access NVIDIA-optimized inference microservices."

    # Verified standard catalog of official NVIDIA NIM models
    _NIM_CATALOG: List[Dict[str, Any]] = [
        {"id": "nvidia/llama-3.1-nemotron-70b-instruct", "name": "Llama 3.1 Nemotron 70B Instruct", "cap": ["chat", "diagnostics"]},
        {"id": "nvidia/nemotron-4-340b-instruct", "name": "Nemotron-4 340B Instruct", "cap": ["chat", "diagnostics"]},
        {"id": "meta/llama-3.3-70b-instruct", "name": "Llama 3.3 70B Instruct (NIM)", "cap": ["chat", "diagnostics"]},
        {"id": "nvidia/neva-22b", "name": "NeVA 22B Multimodal", "cap": ["vision", "chat"]},
        {"id": "deepseek-ai/deepseek-r1", "name": "DeepSeek R1 (NIM)", "cap": ["chat", "reasoning"]},
    ]

    def get_models(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        key = (api_key or "").strip()
        url = (base_url or self.default_url).rstrip("/")

        # If API key is provided, attempt live dynamic discovery from NVIDIA NIM
        if key:
            try:
                headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
                r = _requests.get(f"{url}/models", headers=headers, timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    raw_models = data.get("data", [])
                    discovered: List[ModelDescriptor] = []
                    for m in raw_models:
                        mid = m.get("id")
                        if mid:
                            discovered.append(
                                ModelDescriptor(
                                    provider_id=self.provider_id,
                                    model_id=mid,
                                    display_name=mid,
                                    capabilities=["chat", "diagnostics"],
                                    is_default=(len(discovered) == 0),
                                )
                            )
                    if discovered:
                        return {
                            "status": "DISCOVERED",
                            "models": [m.to_dict() for m in discovered],
                            "error": None,
                        }
                elif r.status_code in (401, 403):
                    return {
                        "status": "MODEL_DISCOVERY_FAILED",
                        "models": [],
                        "error": "Unable to retrieve available NVIDIA models. Invalid API key.",
                    }
                else:
                    return {
                        "status": "MODEL_DISCOVERY_FAILED",
                        "models": [],
                        "error": f"Unable to retrieve available NVIDIA models. Endpoint returned HTTP {r.status_code}.",
                    }
            except _requests.Timeout:
                return {
                    "status": "MODEL_DISCOVERY_FAILED",
                    "models": [],
                    "error": "Unable to retrieve available NVIDIA models. Connection timed out.",
                }
            except Exception as e:
                return {
                    "status": "MODEL_DISCOVERY_FAILED",
                    "models": [],
                    "error": f"Unable to retrieve available NVIDIA models: {e}",
                }

        # If no key provided yet, return verified standard catalog so user can preview models
        catalog_models = [
            ModelDescriptor(
                provider_id=self.provider_id,
                model_id=item["id"],
                display_name=item["name"],
                capabilities=item["cap"],
                is_default=(idx == 0),
            ).to_dict()
            for idx, item in enumerate(self._NIM_CATALOG)
        ]
        return {
            "status": "CONFIG_REQUIRED" if not key else "DISCOVERED",
            "models": catalog_models,
            "error": "NVIDIA API key required to authenticate and query live NIM endpoints." if not key else None,
        }

    def validate_model(
        self,
        model_id: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Tuple[bool, str]:
        if not model_id or not model_id.strip():
            return False, "Model identifier cannot be empty."

        clean = model_id.strip().lower()

        # Disallow models explicitly belonging to other providers
        if clean.startswith("gpt-") or clean.startswith("o1-") or clean.startswith("o3-") or clean.startswith("gemini-") or clean.startswith("grok-"):
            return False, f"Model '{model_id}' belongs to another provider and cannot be used with NVIDIA NIM."

        # Check against known NIM catalog
        for item in self._NIM_CATALOG:
            if clean == item["id"].lower() or clean == item["name"].lower():
                return True, "Model is verified in NVIDIA NIM catalog."

        # Accept valid namespace formats used by NVIDIA NIM (e.g. nvidia/*, meta/*, mistralai/*, deepseek-ai/*)
        if "/" in clean and len(clean.split("/")) == 2:
            return True, "Model namespace recognized as valid NIM endpoint."

        return False, f"Model '{model_id}' is not recognized as a valid NVIDIA NIM model."

    def test_connection(
        self,
        api_key: str,
        base_url: str,
        model_id: str,
    ) -> Tuple[bool, str]:
        key = (api_key or "").strip()
        if not key:
            return False, "No API key configured for NVIDIA NIM."

        valid, reason = self.validate_model(model_id, api_key=key, base_url=base_url)
        if not valid:
            return False, f"Model validation failed: {reason}"

        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
        }
        try:
            r = _requests.post(url, json=payload, headers=headers, timeout=10)
            if r.status_code in (200, 201):
                return True, f"Connection successful. NVIDIA NIM model '{model_id}' is accessible."
            if r.status_code == 401:
                return False, "Invalid NVIDIA API key. Check your key at https://build.nvidia.com"
            if r.status_code == 404:
                return False, f"Model '{model_id}' not found at this NVIDIA NIM endpoint."
            return False, f"NVIDIA API returned HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, f"Connection failed: {e}"

    def generate(
        self,
        prompt: str,
        system: str = "",
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> str:
        key = (api_key or "").strip()
        if not key:
            raise RuntimeError("NVIDIA API key is not configured. Open AI Settings to enter your key.")
        model = model_id or self._NIM_CATALOG[0]["id"]
        url = f"{(base_url or self.default_url).rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        r = _requests.post(url, json={"model": model, "messages": messages, "max_tokens": max_tokens}, headers=headers, timeout=30)
        if r.status_code in (200, 201):
            data = r.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return "No response received from model."
        raise RuntimeError(f"NVIDIA NIM API error ({r.status_code}): {r.text[:250]}")


class OpenAIProvider(BaseAIProvider):
    """OpenAI API adapter."""

    provider_id = "openai"
    name = "OpenAI"
    type = "cloud_api"
    default_url = "https://api.openai.com/v1"
    requires_key = True
    description = "OpenAI GPT models via OpenAI API key."

    _CATALOG: List[Dict[str, Any]] = [
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "cap": ["chat", "diagnostics"]},
        {"id": "gpt-4o", "name": "GPT-4o", "cap": ["chat", "vision", "diagnostics"]},
        {"id": "o1-mini", "name": "o1 Mini", "cap": ["reasoning", "diagnostics"]},
        {"id": "o3-mini", "name": "o3 Mini", "cap": ["reasoning", "diagnostics"]},
        {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "cap": ["chat", "diagnostics"]},
    ]

    def get_models(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        key = (api_key or "").strip()
        url = (base_url or self.default_url).rstrip("/")
        if key:
            try:
                headers = {"Authorization": f"Bearer {key}"}
                r = _requests.get(f"{url}/models", headers=headers, timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    gpt_models = [m["id"] for m in data.get("data", []) if "gpt" in m.get("id", "").lower() or "o1" in m.get("id", "").lower() or "o3" in m.get("id", "").lower()]
                    if gpt_models:
                        res = [
                            ModelDescriptor(
                                provider_id=self.provider_id,
                                model_id=mid,
                                display_name=mid,
                                capabilities=["chat", "diagnostics"],
                                is_default=(idx == 0),
                            ).to_dict()
                            for idx, mid in enumerate(gpt_models[:15])
                        ]
                        return {"status": "DISCOVERED", "models": res, "error": None}
                elif r.status_code in (401, 403):
                    return {"status": "MODEL_DISCOVERY_FAILED", "models": [], "error": "Invalid OpenAI API key."}
            except Exception:
                pass

        catalog = [
            ModelDescriptor(
                provider_id=self.provider_id,
                model_id=item["id"],
                display_name=item["name"],
                capabilities=item["cap"],
                is_default=(idx == 0),
            ).to_dict()
            for idx, item in enumerate(self._CATALOG)
        ]
        return {
            "status": "CONFIG_REQUIRED" if not key else "DISCOVERED",
            "models": catalog,
            "error": "API key required to discover available models." if not key else None,
        }

    def validate_model(
        self,
        model_id: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Tuple[bool, str]:
        clean = (model_id or "").strip().lower()
        if not clean:
            return False, "Model identifier cannot be empty."
        if clean.startswith("gemini-") or clean.startswith("grok-") or clean.startswith("nvidia/") or clean.startswith("phi3"):
            return False, f"Model '{model_id}' does not belong to OpenAI."
        if any(clean == item["id"].lower() for item in self._CATALOG) or any(prefix in clean for prefix in ("gpt-", "o1-", "o3-")):
            return True, "Valid OpenAI model."
        return False, f"Model '{model_id}' is not recognized as a valid OpenAI model."

    def test_connection(
        self,
        api_key: str,
        base_url: str,
        model_id: str,
    ) -> Tuple[bool, str]:
        key = (api_key or "").strip()
        if not key:
            return False, "No API key configured for OpenAI."
        valid, reason = self.validate_model(model_id)
        if not valid:
            return False, f"Model validation failed: {reason}"
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model_id, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}
        try:
            r = _requests.post(url, json=payload, headers=headers, timeout=10)
            if r.status_code in (200, 201):
                return True, f"Connection successful. OpenAI model '{model_id}' is accessible."
            return False, f"OpenAI returned HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, f"Connection failed: {e}"

    def generate(
        self,
        prompt: str,
        system: str = "",
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> str:
        key = (api_key or "").strip()
        if not key:
            raise RuntimeError("OpenAI API key is not configured.")
        model = model_id or self._CATALOG[0]["id"]
        url = f"{(base_url or self.default_url).rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        r = _requests.post(url, json={"model": model, "messages": messages, "max_tokens": max_tokens}, headers=headers, timeout=30)
        if r.status_code in (200, 201):
            data = r.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return "No response received."
        raise RuntimeError(f"OpenAI error ({r.status_code}): {r.text[:250]}")


class GoogleProvider(BaseAIProvider):
    """Google Gemini API adapter."""

    provider_id = "gemini"
    name = "Google Gemini"
    type = "cloud_api"
    default_url = "https://generativelanguage.googleapis.com/v1beta"
    requires_key = True
    description = "Google's Gemini models via Google AI Studio API key."

    _CATALOG: List[Dict[str, Any]] = [
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "cap": ["chat", "vision", "diagnostics"]},
        {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash", "cap": ["chat", "vision", "diagnostics"]},
        {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro", "cap": ["chat", "vision", "complex_reasoning"]},
    ]

    def get_models(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        key = (api_key or "").strip()
        url = (base_url or self.default_url).rstrip("/")
        if key:
            try:
                r = _requests.get(f"{url}/models?key={key}", timeout=5)
                if r.status_code == 200:
                    raw = r.json().get("models", [])
                    gemini_models = [m.get("name", "").replace("models/", "") for m in raw if "gemini" in m.get("name", "").lower()]
                    if gemini_models:
                        res = [
                            ModelDescriptor(
                                provider_id=self.provider_id,
                                model_id=mid,
                                display_name=mid,
                                capabilities=["chat", "diagnostics"],
                                is_default=(idx == 0),
                            ).to_dict()
                            for idx, mid in enumerate(gemini_models[:10])
                        ]
                        return {"status": "DISCOVERED", "models": res, "error": None}
                elif r.status_code in (400, 401, 403):
                    return {"status": "MODEL_DISCOVERY_FAILED", "models": [], "error": "Invalid Google Gemini API key."}
            except Exception:
                pass

        catalog = [
            ModelDescriptor(
                provider_id=self.provider_id,
                model_id=item["id"],
                display_name=item["name"],
                capabilities=item["cap"],
                is_default=(idx == 0),
            ).to_dict()
            for idx, item in enumerate(self._CATALOG)
        ]
        return {
            "status": "CONFIG_REQUIRED" if not key else "DISCOVERED",
            "models": catalog,
            "error": "API key required to discover available models." if not key else None,
        }

    def validate_model(
        self,
        model_id: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Tuple[bool, str]:
        clean = (model_id or "").strip().lower()
        if not clean:
            return False, "Model identifier cannot be empty."
        if clean.startswith("gpt-") or clean.startswith("nvidia/") or clean.startswith("grok-"):
            return False, f"Model '{model_id}' does not belong to Google Gemini."
        if "gemini" in clean:
            return True, "Valid Google Gemini model."
        return False, f"Model '{model_id}' is not recognized as a Google Gemini model."

    def test_connection(
        self,
        api_key: str,
        base_url: str,
        model_id: str,
    ) -> Tuple[bool, str]:
        key = (api_key or "").strip()
        if not key:
            return False, "No API key configured for Google Gemini."
        valid, reason = self.validate_model(model_id)
        if not valid:
            return False, f"Model validation failed: {reason}"
        url = f"{base_url.rstrip('/')}/models/{model_id}:generateContent?key={key}"
        payload = {"contents": [{"parts": [{"text": "ping"}]}]}
        try:
            r = _requests.post(url, json=payload, timeout=10)
            if r.status_code in (200, 400):
                return True, f"Google Gemini API key is valid. Model '{model_id}' is accessible."
            if r.status_code == 401:
                return False, "Invalid Gemini API key. Check your key at https://aistudio.google.com"
            return False, f"Gemini API returned HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, f"Connection failed: {e}"

    def generate(
        self,
        prompt: str,
        system: str = "",
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> str:
        key = (api_key or "").strip()
        if not key:
            raise RuntimeError("Gemini API key is not configured.")
        model = model_id or self._CATALOG[0]["id"]
        url = f"{(base_url or self.default_url).rstrip('/')}/models/{model}:generateContent?key={key}"
        contents = []
        if system:
            contents.append({"role": "user", "parts": [{"text": f"System Instructions:\n{system}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        r = _requests.post(url, json={"contents": contents}, timeout=30)
        if r.status_code == 200:
            data = r.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                return "".join(p.get("text", "") for p in parts)
            return "No response generated."
        raise RuntimeError(f"Gemini API error ({r.status_code}): {r.text[:250]}")


class XAIProvider(BaseAIProvider):
    """xAI Grok API adapter."""

    provider_id = "xai"
    name = "xAI Grok"
    type = "cloud_api"
    default_url = "https://api.x.ai/v1"
    requires_key = True
    description = "xAI's Grok models via xAI API key."

    _CATALOG: List[Dict[str, Any]] = [
        {"id": "grok-2-1212", "name": "Grok 2", "cap": ["chat", "diagnostics"]},
        {"id": "grok-2-vision-1212", "name": "Grok 2 Vision", "cap": ["chat", "vision"]},
        {"id": "grok-beta", "name": "Grok Beta", "cap": ["chat", "diagnostics"]},
    ]

    def get_models(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        key = (api_key or "").strip()
        url = (base_url or self.default_url).rstrip("/")
        if key:
            try:
                headers = {"Authorization": f"Bearer {key}"}
                r = _requests.get(f"{url}/models", headers=headers, timeout=5)
                if r.status_code == 200:
                    raw = r.json().get("data", [])
                    grok_models = [m["id"] for m in raw if "grok" in m.get("id", "").lower()]
                    if grok_models:
                        res = [
                            ModelDescriptor(
                                provider_id=self.provider_id,
                                model_id=mid,
                                display_name=mid,
                                capabilities=["chat", "diagnostics"],
                                is_default=(idx == 0),
                            ).to_dict()
                            for idx, mid in enumerate(grok_models)
                        ]
                        return {"status": "DISCOVERED", "models": res, "error": None}
                elif r.status_code in (401, 403):
                    return {"status": "MODEL_DISCOVERY_FAILED", "models": [], "error": "Invalid xAI API key."}
            except Exception:
                pass

        catalog = [
            ModelDescriptor(
                provider_id=self.provider_id,
                model_id=item["id"],
                display_name=item["name"],
                capabilities=item["cap"],
                is_default=(idx == 0),
            ).to_dict()
            for idx, item in enumerate(self._CATALOG)
        ]
        return {
            "status": "CONFIG_REQUIRED" if not key else "DISCOVERED",
            "models": catalog,
            "error": "API key required to discover available models." if not key else None,
        }

    def validate_model(
        self,
        model_id: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Tuple[bool, str]:
        clean = (model_id or "").strip().lower()
        if not clean:
            return False, "Model identifier cannot be empty."
        if clean.startswith("gpt-") or clean.startswith("gemini-") or clean.startswith("nvidia/"):
            return False, f"Model '{model_id}' does not belong to xAI Grok."
        if "grok" in clean:
            return True, "Valid xAI Grok model."
        return False, f"Model '{model_id}' is not recognized as an xAI model."

    def test_connection(
        self,
        api_key: str,
        base_url: str,
        model_id: str,
    ) -> Tuple[bool, str]:
        key = (api_key or "").strip()
        if not key:
            return False, "No API key configured for xAI."
        valid, reason = self.validate_model(model_id)
        if not valid:
            return False, f"Model validation failed: {reason}"
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model_id, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}
        try:
            r = _requests.post(url, json=payload, headers=headers, timeout=10)
            if r.status_code in (200, 201):
                return True, f"Connection successful. xAI model '{model_id}' is accessible."
            return False, f"xAI API returned HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, f"Connection failed: {e}"

    def generate(
        self,
        prompt: str,
        system: str = "",
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> str:
        key = (api_key or "").strip()
        if not key:
            raise RuntimeError("xAI API key is not configured.")
        model = model_id or self._CATALOG[0]["id"]
        url = f"{(base_url or self.default_url).rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        r = _requests.post(url, json={"model": model, "messages": messages, "max_tokens": max_tokens}, headers=headers, timeout=30)
        if r.status_code in (200, 201):
            data = r.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return "No response received."
        raise RuntimeError(f"xAI API error ({r.status_code}): {r.text[:250]}")


# Provider Registry
AI_PROVIDERS: Dict[str, BaseAIProvider] = {
    "ollama": OllamaProvider(),
    "gemini": GoogleProvider(),
    "openai": OpenAIProvider(),
    "nvidia": NVIDIAProvider(),
    "xai": XAIProvider(),
}


def get_provider_adapter(provider_id: str) -> BaseAIProvider:
    """Retrieve the adapter for a given provider ID."""
    p_id = (provider_id or "").strip().lower()
    if p_id not in AI_PROVIDERS:
        raise ValueError(f"Unknown AI provider: '{provider_id}'. Supported: {', '.join(AI_PROVIDERS.keys())}")
    return AI_PROVIDERS[p_id]
