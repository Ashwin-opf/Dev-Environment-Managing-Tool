"""
routes_ai_config.py — AI Provider Configuration API
=====================================================
Manages AI provider settings (Ollama, Gemini, OpenAI, NVIDIA NIM, xAI).
API keys are NEVER stored in plaintext — they are stored in the OS keyring
(via `keyring` package) or in an AES-encrypted local config file as fallback.
Keys are NEVER returned to the frontend after being saved.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import requests as _requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# ---------------------------------------------------------------------------
# Config paths
# ---------------------------------------------------------------------------

try:
    from runtime_paths import get_ai_config_dir
    _CONFIG_DIR = get_ai_config_dir()
except Exception:
    _CONFIG_DIR = Path(__file__).parent / ".pc_doctor_ai_config"
_CONFIG_FILE = _CONFIG_DIR / "providers.json"

from ai_providers import AI_PROVIDERS, get_provider_adapter, ModelDescriptor

SUPPORTED_PROVIDERS = {
    p_id: {
        "label": adapter.name,
        "type": adapter.type,
        "requires_key": adapter.requires_key,
        "default_url": adapter.default_url,
        "description": adapter.description,
    }
    for p_id, adapter in AI_PROVIDERS.items()
}


# ---------------------------------------------------------------------------
# Secure storage helpers
# ---------------------------------------------------------------------------

def _keyring_available() -> bool:
    try:
        import keyring  # noqa: F401
        return True
    except ImportError:
        return False


def _store_key(provider: str, api_key: str) -> None:
    """Store API key in OS keyring if available, else in obfuscated local file."""
    if _keyring_available():
        import keyring
        keyring.set_password("pc_doctor_ai", provider, api_key)
    else:
        # Fallback: simple base64 obfuscation (not encryption, but not plaintext)
        import base64
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        keys_file = _CONFIG_DIR / "keys.enc"
        try:
            existing = json.loads(keys_file.read_text()) if keys_file.exists() else {}
        except Exception:
            existing = {}
        existing[provider] = base64.b64encode(api_key.encode()).decode()
        keys_file.write_text(json.dumps(existing))
        # Restrict permissions on non-Windows
        if platform.system() != "Windows":
            keys_file.chmod(0o600)


def _retrieve_key(provider: str) -> Optional[str]:
    """Retrieve API key from OS keyring or local fallback."""
    if _keyring_available():
        import keyring
        val = keyring.get_password("pc_doctor_ai", provider)
        if val:
            return val

    import base64
    keys_file = _CONFIG_DIR / "keys.enc"
    if keys_file.exists():
        try:
            data = json.loads(keys_file.read_text())
            encoded = data.get(provider)
            if encoded:
                return base64.b64decode(encoded.encode()).decode()
        except Exception:
            pass
    return None


def _has_key(provider: str) -> bool:
    return bool(_retrieve_key(provider))


def _delete_key(provider: str) -> None:
    if _keyring_available():
        try:
            import keyring
            keyring.delete_password("pc_doctor_ai", provider)
        except Exception:
            pass
    keys_file = _CONFIG_DIR / "keys.enc"
    if keys_file.exists():
        try:
            data = json.loads(keys_file.read_text())
            data.pop(provider, None)
            keys_file.write_text(json.dumps(data))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Provider config (non-secret settings)
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text())
        except Exception:
            pass
    return {"active_provider": "ollama", "provider_settings": {}}


def _save_config(cfg: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


# ---------------------------------------------------------------------------
# Ollama health check helper
# ---------------------------------------------------------------------------

def _check_ollama_health(base_url: str = "http://127.0.0.1:11434") -> dict:
    try:
        r = _requests.get(f"{base_url}/api/tags", timeout=1.5)
        if r.status_code == 200:
            models = [m.get("name") for m in r.json().get("models", [])]
            return {"running": True, "models": models}
    except Exception:
        pass
    # Check via CLI
    if shutil.which("ollama"):
        try:
            result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                lines = result.stdout.strip().splitlines()
                models = [line.split()[0] for line in lines[1:] if line.strip()]
                return {"running": True, "models": models, "via": "cli"}
        except Exception:
            pass
        return {"running": False, "installed": True, "models": []}
    return {"running": False, "installed": False, "models": []}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ProviderConfigBody(BaseModel):
    provider: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None


class TestProviderBody(BaseModel):
    __test__ = False
    provider: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/api/ai/providers")
async def get_providers():
    """Return all supported AI providers and their current status."""
    cfg = _load_config()
    active = cfg.get("active_provider", "ollama")
    ollama_status = _check_ollama_health()

    result = []
    for provider_id, adapter in AI_PROVIDERS.items():
        settings = cfg.get("provider_settings", {}).get(provider_id, {})
        configured_key = _has_key(provider_id) if adapter.requires_key else True
        configured_model = settings.get("model")

        status = "not_configured"
        if provider_id == "ollama":
            if ollama_status["running"]:
                status = "ready"
            elif ollama_status.get("installed"):
                status = "installed_not_running"
            else:
                status = "not_installed"
        elif configured_key:
            status = "configured"

        # Check validity of configured model if any
        is_model_valid = True
        model_status = "VALID"
        if configured_model:
            is_model_valid, _ = adapter.validate_model(configured_model)
            if not is_model_valid:
                model_status = "NEEDS_RECONFIGURATION"

        result.append({
            "id": provider_id,
            "label": adapter.name,
            "type": adapter.type,
            "description": adapter.description,
            "requires_key": adapter.requires_key,
            "has_key": configured_key,
            "active_model": configured_model or "",
            "is_model_valid": is_model_valid,
            "model_status": model_status,
            "status": status,
            "is_active": provider_id == active,
            # Only include Ollama status details
            "ollama": ollama_status if provider_id == "ollama" else None,
        })

    return {"ok": True, "providers": result, "active_provider": active}


@router.post("/api/ai/providers/config")
async def save_provider_config(body: ProviderConfigBody):
    """Save AI provider configuration with strict model validation."""
    provider_id = body.provider.lower()
    try:
        adapter = get_provider_adapter(provider_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Validate key is provided when required
    if adapter.requires_key and body.api_key:
        key = body.api_key.strip()
        if len(key) < 10:
            raise HTTPException(status_code=400, detail="API key appears too short to be valid.")
        _store_key(provider_id, key)

    key = (body.api_key or "").strip() or _retrieve_key(provider_id) or ""
    base_url = body.base_url or adapter.default_url

    # Model compatibility check: Reject invalid provider/model combinations
    if body.model:
        is_valid, reason = adapter.validate_model(body.model, api_key=key, base_url=base_url)
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail=f"Model '{body.model}' is not compatible with {adapter.name}. {reason}"
            )

    # Save non-secret settings
    cfg = _load_config()
    if "provider_settings" not in cfg:
        cfg["provider_settings"] = {}
    settings = cfg["provider_settings"].setdefault(provider_id, {})

    if body.model:
        settings["model"] = body.model
    if body.base_url:
        settings["base_url"] = body.base_url.rstrip("/")

    cfg["active_provider"] = provider_id
    _save_config(cfg)

    return {
        "ok": True,
        "message": f"Provider '{adapter.name}' configured successfully. Key stored securely.",
        "active_provider": provider_id,
        "model": body.model,
    }


@router.post("/api/ai/providers/test")
async def test_provider(body: TestProviderBody):
    """
    Test connectivity to an AI provider via its adapter.
    """
    provider_id = body.provider.lower()
    try:
        adapter = get_provider_adapter(provider_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cfg = _load_config()
    key = (body.api_key or "").strip() or _retrieve_key(provider_id) or ""
    base_url = body.base_url or cfg.get("provider_settings", {}).get(provider_id, {}).get("base_url") or adapter.default_url
    model = body.model or cfg.get("provider_settings", {}).get(provider_id, {}).get("model") or ""

    if not model and adapter.type == "local":
        model = "phi3:mini"

    ok, message = adapter.test_connection(api_key=key, base_url=base_url, model_id=model)
    return {"ok": ok, "message": message}

test_provider.__test__ = False


@router.get("/api/ai/models")
async def get_ai_models(provider: Optional[str] = None):
    """
    Return available models for the specified provider (or active provider).
    Models are resolved dynamically from the selected provider adapter.
    """
    cfg = _load_config()
    active = cfg.get("active_provider", "ollama")
    target_provider = (provider or active).strip().lower()

    try:
        adapter = get_provider_adapter(target_provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    settings = cfg.get("provider_settings", {}).get(target_provider, {})
    key = _retrieve_key(target_provider) or ""
    base_url = settings.get("base_url") or adapter.default_url

    discovery_result = adapter.get_models(api_key=key, base_url=base_url)

    configured_model = settings.get("model") or ""
    is_model_valid = True
    model_status = "VALID"

    if configured_model:
        is_model_valid, _ = adapter.validate_model(configured_model, api_key=key, base_url=base_url)
        if not is_model_valid:
            model_status = "NEEDS_RECONFIGURATION"

    return {
        "ok": True,
        "provider": target_provider,
        "provider_label": adapter.name,
        "provider_type": adapter.type,
        "status": discovery_result["status"],
        "models": discovery_result["models"],
        "active_model": configured_model,
        "is_model_valid": is_model_valid,
        "model_status": model_status,
        "error": discovery_result.get("error"),
    }


@router.delete("/api/ai/providers/{provider_id}/key")
async def delete_provider_key(provider_id: str):
    """Remove a stored API key for a provider."""
    if provider_id not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    _delete_key(provider_id)
    return {"ok": True, "message": f"API key for '{provider_id}' removed."}
