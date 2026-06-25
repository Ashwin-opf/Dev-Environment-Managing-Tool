import asyncio
import functools
import platform
import shutil
import subprocess
import requests as _requests
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_assistant import ask_ollama

router = APIRouter()


class AIRequest(BaseModel):
    prompt: str
    model: str = "phi3:mini"


AGENT_SYSTEM_PROMPT = """You are PC Doctor Agent, an expert autonomous Linux/Windows system repair agent.
The user will describe a PC problem in plain English. Your job is to:

1. DIAGNOSE the root cause concisely (2-3 sentences max) using step-by-step reasoning.
2. PRESCRIBE the exact terminal commands that will fix the problem.
3. ALWAYS wrap commands in ```bash code blocks so they can be extracted and executed.
4. Give ONE command per line inside the code block.
5. Explain briefly what each command does (one sentence, outside the code block).
6. If a command requires sudo, include sudo.
7. If you need more info to diagnose, give a diagnostic command first (e.g. `which python3`, `systemctl status docker`).
8. After showing commands, ask the user to report the output so you can continue diagnosing.

IMPORTANT RULES:
- You are running on {os_name} ({os_version}).
- Distro/Profile context: {os_profile}
- Show only newer/latest versions of packages or apps. Always recommend installing or updating to the latest stable version of any package.
- If recommending multiple steps, always prefix each executable command with a comment line inside the bash block mapping it to its step and purpose, e.g.:
  # Step 1: Install prerequisites
  sudo apt-get install -y build-essential
  # Step 2: Download the source package
  wget https://example.com/src.tar.gz
- NEVER suggest commands that could cause data loss without warning.
- NEVER suggest unloading, removing, or disabling active kernel modules or hardware drivers (e.g. do NOT suggest `modprobe -r`, `modprobe --remove`, or `rmmod`).
- NEVER suggest commands that disconnect essential hardware, USB controllers, storage drives, or network interfaces.
- If a hardware driver or kernel state needs reloading or resetting, recommend a standard system reboot or package update instead of live module unloading.
- Always prefer the native package manager for the current OS: winget/choco on Windows, apt/dnf/pacman/snap/flatpak on Linux as appropriate, and softwareupdate/brew on macOS.
- Be concise and action-oriented. No fluff.
- If the user gives you command output, analyze it and suggest the next step.

Example response format:
---
Your pip installation seems broken. Let me fix it:

```bash
# Step 1: Reinstall pip from system repository
sudo apt-get install -y python3-pip
# Step 2: Upgrade pip to the latest version
python3 -m pip install --upgrade pip
```

The first command reinstalls pip from your system's package manager.
The second upgrades pip to the latest version.

Run these and tell me what you see!
---
"""


@router.post("/api/ai")
async def ai_chat(request: AIRequest):
    """Send a natural-language prompt to the local Ollama model."""
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, functools.partial(ask_ollama, request.prompt, model=request.model)
        )
        return {"ok": True, "response": response}
    except (subprocess.TimeoutExpired, _requests.Timeout):
        raise HTTPException(
            status_code=408,
            detail="Model is taking too long to respond. The model may still be loading. Please try again in a moment."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/ai_agent")
async def ai_agent(request: AIRequest):
    """Agentic AI endpoint: diagnoses problems and suggests executable commands."""
    from app_context import engine
    from command_adaptation import detect_os_profile

    # Gather system context
    os_name = platform.system()
    profile = detect_os_profile(engine)
    os_label = profile.get("os_label", "")
    os_version = profile.get("version", "") or profile.get("os_version", "") or platform.version()
    kernel = profile.get("kernel", "")
    package_manager = profile.get("package_manager", "")

    os_profile = f"OS Label: {os_label}, Version: {os_version}, Kernel: {kernel}, Package Manager: {package_manager}"

    # Build the agent system prompt with real system info
    system = AGENT_SYSTEM_PROMPT.format(
        os_name=os_name,
        os_version=os_version,
        os_profile=os_profile
    )

    # Gather installed tool status for context
    from tool_detector import (
        python_installed, pip_installed, node_installed, npm_installed,
        git_installed, docker_installed, vscode_installed, java_installed,
        snap_installed, android_studio_installed, poetry_installed, pnpm_installed,
        ollama_installed
    )
    tools_status = {
        "python3": python_installed(),
        "pip": pip_installed(),
        "node": node_installed(),
        "npm": npm_installed(),
        "git": git_installed(),
        "docker": docker_installed(),
        "vscode (code)": vscode_installed(),
        "java": java_installed(),
        "snap": snap_installed(),
        "android-studio": android_studio_installed(),
        "poetry": poetry_installed(),
        "pnpm": pnpm_installed(),
        "ollama": ollama_installed(),
    }
    for cli_tool in ["rustc", "go", "htop", "nvim", "gh", "fzf", "jq", "tmux", "pycharm", "subl", "postman", "dbeaver", "slack", "brave", "google-chrome", "firefox"]:
        tools_status[cli_tool] = shutil.which(cli_tool) is not None or shutil.which(cli_tool + "-community") is not None
        
    tools_context = [f"  {name}: {'✓ installed' if present else '✗ not found'}" for name, present in tools_status.items()]
    tools_str = "\n".join(tools_context)

    # Augment the user prompt with system context
    augmented_prompt = (
        f"[System Info]\n"
        f"OS: {os_name} {os_version}\n"
        f"Installed tools:\n{tools_str}\n\n"
        f"[User Problem]\n{request.prompt}"
    )

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, functools.partial(ask_ollama, augmented_prompt, model=request.model, system=system)
        )
        return {"ok": True, "response": response}
    except (subprocess.TimeoutExpired, _requests.Timeout):
        raise HTTPException(
            status_code=408,
            detail="Model is taking too long to respond. The model may still be loading. Please try again in a moment."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

