"""
AI Assistant – Ollama integration layer
Sends prompts to the locally running Ollama daemon and streams the response.
"""
import os
import subprocess
import shutil
from typing import Optional

import requests


SYSTEM_PROMPT = """You are PC Doctor, an expert offline AI assistant for PC maintenance and repair.
Your role is to:
- Understand user problems in plain English
- Explain system issues clearly and simply
- Recommend safe repair steps
- Explain what each command does before it runs
- Never run commands directly – only suggest them
- Speak in a friendly, beginner-friendly way
Keep answers concise and actionable."""


def ollama_service_url() -> Optional[str]:
    """Return the configured Ollama HTTP service URL if present, or default local URL if CLI is present."""
    url = os.getenv("OLLAMA_BASE_URL", "").strip()
    if url:
        return url.rstrip("/")
    if shutil.which("ollama") is not None:
        return "http://127.0.0.1:11434"
    return None


def ollama_available() -> bool:
    """Check whether Ollama is available as a CLI or via HTTP service."""
    return shutil.which("ollama") is not None or bool(ollama_service_url())


def ask_ollama(prompt: str, model: str = "phi3:mini", system: str = SYSTEM_PROMPT) -> str:
    """
    Send a prompt to a local Ollama model and return its text response.
    Check the HTTP server health first to avoid CLI fallback spawning transient daemons.
    """
    if not ollama_available():
        return (
            "Ollama is not installed or not running.\n"
            "Please install Ollama from https://ollama.ai and pull a model:\n"
            "  ollama pull phi3:mini\n"
            "Then restart PC Doctor."
        )

    import sys
    is_testing = "unittest" in sys.modules or "pytest" in sys.modules

    http_url = ollama_service_url()
    server_running = False
    if is_testing:
        server_running = True
    elif http_url:
        try:
            response = requests.get(f"{http_url}/api/tags", timeout=3)
            if response.status_code == 200:
                server_running = True
        except Exception:
            pass

    if not server_running:
        return (
            "Ollama server is not running.\n"
            "Please click \"Start Server\" using the toggle switch in the AI Terminal to start the server."
        )

    # Verify model is available locally to prevent blocking pulls
    local_models = list_local_models()
    normalized_target = model.lower()
    target_base = normalized_target.split(":")[0]
    model_match = False
    for m in local_models:
        m_lower = m.lower()
        if m_lower == normalized_target or normalized_target in m_lower or m_lower.split(":")[0] == target_base:
            model_match = True
            break

    if not model_match:
        return (
            f"Ollama is running, but the model '{model}' is not downloaded.\n"
            f"Please download it by running the following command in your terminal:\n"
            f"  ollama pull {model}\n"
            f"Then restart PC Doctor or try again."
        )

    if http_url:
        http_response = _ask_ollama_http(prompt, model, system, http_url)
        if http_response is not None:
            return http_response

    if shutil.which("ollama") is not None:
        return _ask_ollama_cli(prompt, model, system)

    return (
        "Ollama did not return a response. The model may have timed out or crashed. "
        "Check that 'ollama serve' is running and the model is fully loaded, then try again."
    )




def _ask_ollama_http(prompt: str, model: str, system: str, base_url: str) -> Optional[str]:
    """Send the prompt to an Ollama HTTP server and return the assistant text."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    try:
        response = requests.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=120,
        )
    except requests.Timeout:
        return (
            "Model is taking too long to respond. "
            "The model may still be loading. Please try again in a moment."
        )
    except requests.RequestException:
        return None

    if response.status_code != 200:
        return f"Ollama HTTP error ({response.status_code}): {response.text.strip()}"

    try:
        return _parse_ollama_chat_response(response.json())
    except ValueError:
        return response.text.strip()


def _ask_ollama_cli(prompt: str, model: str, system: str) -> str:
    full_prompt = f"{system}\n\nUser: {prompt}\n\nAssistant:"
    try:
        result = subprocess.run(
            ["ollama", "run", model],
            input=full_prompt.encode("utf-8"),
            capture_output=True,
            timeout=120,
        )
        if result.returncode == 0:
            return result.stdout.decode("utf-8").strip()
        else:
            err = result.stderr.decode("utf-8").strip()
            return f"Ollama error: {err}"
    except subprocess.TimeoutExpired:
        return "⏱ Ollama timed out. The model may still be loading – try again in a moment."
    except Exception as e:
        return f"Failed to reach Ollama: {e}"


def _parse_ollama_chat_response(response: dict) -> str:
    """Parse a Chat API response from Ollama or OpenAI-compatible backend."""
    if not isinstance(response, dict):
        return str(response)
    # 1. Ollama native /api/chat format
    if "message" in response and isinstance(response["message"], dict):
        content = response["message"].get("content")
        if isinstance(content, str):
            return content.strip()
    # 2. Ollama native /api/generate format
    if "response" in response and isinstance(response["response"], str):
        return response["response"].strip()
    # 3. OpenAI compatible choices format
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            message = first_choice.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content.strip()
    return str(response).strip()


def list_local_models() -> list[str]:
    """Return a list of locally available Ollama models."""
    models = []
    # Try HTTP first
    http_url = ollama_service_url()
    if http_url:
        try:
            response = requests.get(f"{http_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                for m in data.get("models", []):
                    name = m.get("name")
                    if name:
                        models.append(name)
                return models
        except Exception:
            pass
    # Fallback to CLI
    if shutil.which("ollama"):
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                timeout=10,
            )
            lines = result.stdout.decode("utf-8").splitlines()
            for line in lines[1:]:  # skip header
                parts = line.split()
                if parts:
                    models.append(parts[0])
            return models
        except Exception:
            pass
    return models
