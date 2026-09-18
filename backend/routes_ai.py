import asyncio
import functools
import platform
import shutil
import subprocess
import psutil
import requests as _requests
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ai_assistant import ask_ollama

router = APIRouter()


class AIRequest(BaseModel):
    prompt: str
    model: str = "phi3:mini"


class ChatRequest(BaseModel):
    message: str
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

CHAT_SYSTEM_PROMPT = """You are PC Doctor, an expert AI assistant for system diagnostics, repair, and developer environment management.

You are running on {os_name}. Current system health:
{system_health}

Your role:
- Analyze system problems described in plain English
- Explain issues clearly and concisely
- Suggest safe, specific repair steps
- Use structured format: Problem, Cause, Solution, Command (when relevant)
- Be direct and actionable — no unnecessary padding

For general conversation (greetings, non-technical questions): respond naturally and briefly.
For system/technical questions: provide structured diagnosis with specific commands.
For "why is X high / slow / broken": use the real system metrics above to give a data-driven answer.

IMPORTANT: Only reference system health metrics when the user's question is about system performance.
Do NOT append system health information to greetings or unrelated questions.
"""


def _is_system_health_query(message: str) -> bool:
    """Detect if the message is asking about system performance/health."""
    lower = message.lower()
    health_keywords = [
        "ram", "memory", "cpu", "processor", "gpu", "disk", "storage",
        "slow", "high usage", "performance", "lag", "freeze", "crash",
        "docker", "daemon", "service", "error", "python", "health",
        "diagnose", "troubleshoot", "fix", "repair", "not working",
        "environment", "version", "installed", "missing", "broken",
        "startup", "boot", "network", "connection", "timeout",
    ]
    return any(kw in lower for kw in health_keywords)


def _get_system_health_context() -> str:
    """Gather real-time system metrics for AI context."""
    lines = []
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        lines.append(f"CPU Usage: {cpu:.1f}%")
    except Exception:
        lines.append("CPU Usage: unavailable")

    try:
        mem = psutil.virtual_memory()
        lines.append(
            f"RAM Usage: {mem.percent:.1f}% "
            f"({round((mem.total - mem.available) / 1024**3, 1)} GB used / "
            f"{round(mem.total / 1024**3, 1)} GB total)"
        )
    except Exception:
        lines.append("RAM Usage: unavailable")

    try:
        disk = psutil.disk_usage("C:\\" if platform.system() == "Windows" else "/")
        lines.append(f"Disk Usage: {disk.percent:.1f}% ({round(disk.free / 1024**3, 1)} GB free)")
    except Exception:
        lines.append("Disk Usage: unavailable")

    # Check key developer tools
    tool_checks = {
        "Docker": ["docker", "--version"],
        "Python": ["python", "--version"],
        "Node.js": ["node", "--version"],
        "Git": ["git", "--version"],
    }
    tool_status = []
    for name, cmd in tool_checks.items():
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            ver = (r.stdout or r.stderr or "").strip().split("\n")[0][:40]
            tool_status.append(f"  {name}: {ver or 'installed'}")
        except Exception:
            if shutil.which(cmd[0]):
                tool_status.append(f"  {name}: installed (version unavailable)")
            else:
                tool_status.append(f"  {name}: not found")

    if tool_status:
        lines.append("Developer Tools:\n" + "\n".join(tool_status))

    return "\n".join(lines) if lines else "System metrics unavailable"


def _dispatch_ai_query(prompt: str, system: str = "", requested_model: Optional[str] = None) -> str:
    """Dispatches prompt to the active AI provider adapter."""
    from routes_ai_config import _load_config, _retrieve_key
    from ai_providers import get_provider_adapter

    cfg = _load_config()
    provider_id = cfg.get("active_provider", "ollama")
    try:
        adapter = get_provider_adapter(provider_id)
    except ValueError:
        adapter = get_provider_adapter("ollama")

    settings = cfg.get("provider_settings", {}).get(provider_id, {})
    model = requested_model or settings.get("model") or ""
    base_url = settings.get("base_url") or adapter.default_url
    key = _retrieve_key(provider_id) or ""

    try:
        return adapter.generate(
            prompt=prompt,
            system=system,
            model_id=model,
            api_key=key,
            base_url=base_url,
        )
    except Exception as e:
        if adapter.type == "local":
            return _generate_contextual_diagnostic_fallback(prompt)
        raise e


def _generate_contextual_diagnostic_fallback(prompt: str) -> str:
    """Provides high-quality, contextual local diagnostic replies when no LLM provider is reachable."""
    import psutil
    p_lower = prompt.lower().strip()

    if p_lower in ("hi", "hello", "hey", "greetings", "hi there", "hello there"):
        return (
            "Hello! I am PC Doctor AI Assistant. I can help diagnose hardware usage, "
            "troubleshoot Docker and runtime services, inspect package manager health, "
            "and suggest verified commands to optimize your environment. What would you like to investigate today?"
        )

    if any(k in p_lower for k in ("ram", "memory", "high ram")):
        try:
            mem = psutil.virtual_memory()
            ram_pct = mem.percent
            ram_used_gb = round((mem.total - mem.available) / (1024**3), 1)
            ram_total_gb = round(mem.total / (1024**3), 1)
            procs = []
            for p in sorted(psutil.process_iter(['name', 'memory_info']), key=lambda x: (x.info['memory_info'].rss if x.info['memory_info'] else 0), reverse=True)[:5]:
                try:
                    mb = round(p.info['memory_info'].rss / (1024**2), 1)
                    procs.append(f"- **{p.info['name']}**: {mb} MB")
                except Exception:
                    pass
            procs_str = "\n".join(procs) if procs else "- System processes running"
            return (
                f"### RAM Usage Analysis\n\n"
                f"Your system is currently utilizing **{ram_pct}%** of RAM ({ram_used_gb} GB used out of {ram_total_gb} GB total).\n\n"
                f"**Top Memory Consumers:**\n{procs_str}\n\n"
                f"**Root Cause:** Working sets and cached standby memory remain allocated by active processes and background runtimes.\n\n"
                f"**Recommended Action:** Clear standby cache and force working set garbage collection:\n\n"
                f"```powershell\n[GC]::Collect(); [GC]::WaitForPendingFinalizers()\n```"
            )
        except Exception:
            return (
                "### RAM Usage Analysis\n\n"
                "RAM usage is elevated due to active running processes and cached standby pages.\n\n"
                "```powershell\n[GC]::Collect(); [GC]::WaitForPendingFinalizers()\n```"
            )

    if "docker" in p_lower:
        is_windows = platform.system() == "Windows"
        cmd = "wsl --shutdown; net start com.docker.service" if is_windows else "sudo systemctl restart docker"
        return (
            "### Docker Daemon Diagnostic\n\n"
            "**Problem:** Docker daemon service is stopped or unreachable.\n\n"
            "**Cause:** The Docker background service or WSL2 virtual machine subsystem requires restart.\n\n"
            "**Solution:** Restart the Docker service:\n\n"
            f"```powershell\n{cmd}\n```"
        )

    if any(k in p_lower for k in ("dns", "network", "slow internet", "latency")):
        return (
            "### Network & DNS Diagnostic\n\n"
            "**Problem:** DNS lookup latency or stale name resolution cache.\n\n"
            "**Cause:** The local DNS resolver cache contains expired or slow responding entries.\n\n"
            "**Solution:** Flush the local DNS resolver cache to renew lookups:\n\n"
            "```powershell\nipconfig /flushdns\n```"
        )

    # General conversational fallback
    return (
        f"I received your request regarding: **{prompt}**.\n\n"
        "To enable full multi-turn generative AI, click **⚙ AI Settings** above to configure Google Gemini (free API key from AI Studio) or connect to OpenAI / local Ollama."
    )


@router.post("/api/chat")
async def ai_chat_simple(request: ChatRequest):
    """
    Frontend-facing chat endpoint.
    Provides context-aware responses:
    - For system health questions: includes real CPU/RAM/disk metrics + tool status
    - For general questions: responds naturally without injecting system data
    """
    message = (request.message or "").strip()
    if not message:
        return {"ok": True, "reply": "Please enter a question."}

    include_health = _is_system_health_query(message)

    if include_health:
        loop = asyncio.get_event_loop()
        health_ctx = await loop.run_in_executor(None, _get_system_health_context)
    else:
        health_ctx = "Not queried (general conversation)"

    os_name = platform.system()
    system_prompt = CHAT_SYSTEM_PROMPT.format(
        os_name=os_name,
        system_health=health_ctx,
    )

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, functools.partial(_dispatch_ai_query, message, system=system_prompt, requested_model=request.model)
        )
        return {"ok": True, "reply": response, "response": response}
    except (subprocess.TimeoutExpired, _requests.Timeout):
        raise HTTPException(
            status_code=408,
            detail="Model is taking too long to respond. The provider may be experiencing high latency. Please try again in a moment.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/ai")
async def ai_chat(request: AIRequest):
    """Send a natural-language prompt to the configured AI model."""
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, functools.partial(_dispatch_ai_query, request.prompt, requested_model=request.model)
        )
        return {"ok": True, "response": response}
    except (subprocess.TimeoutExpired, _requests.Timeout):
        raise HTTPException(
            status_code=408,
            detail="Model is taking too long to respond. Please try again in a moment.",
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
        os_profile=os_profile,
    )

    # Gather installed tool status for context
    from tool_detector import (
        python_installed, pip_installed, node_installed, npm_installed,
        git_installed, docker_installed, vscode_installed, java_installed,
        snap_installed, android_studio_installed, poetry_installed, pnpm_installed,
        ollama_installed,
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

    tools_context = [f"  {name}: {'installed' if present else 'not found'}" for name, present in tools_status.items()]
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
            None, functools.partial(_dispatch_ai_query, augmented_prompt, system=system, requested_model=request.model)
        )
        return {"ok": True, "response": response}
    except (subprocess.TimeoutExpired, _requests.Timeout):
        raise HTTPException(
            status_code=408,
            detail="Model is taking too long to respond. The model may still be loading. Please try again in a moment.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

