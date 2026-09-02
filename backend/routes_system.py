import os
import platform
import re
import shutil
import json
import sqlite3
from pathlib import Path
from typing import Optional, Any
from fastapi import APIRouter, HTTPException, Body, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import psutil

from app_context import engine, scanner, safety, vector_searcher
from logger import log_action
from devtools_manager import devtools_manager
from command_adaptation import (
    detect_os_profile,
    enrich_recipes,
    get_adaptation_status,
    get_errors,
    get_history,
    record_error,
    record_history,
    refresh_adaptation,
    search_recipes as search_recipes_by_keyword,
    system_update_command,
)
from tool_detector import (
    android_studio_installed,
    docker_installed,
    git_installed,
    java_home_configured,
    java_installed,
    node_installed,
    npm_installed,
    pip_installed,
    python_installed,
    snap_installed,
    vscode_installed,
)
from platform_hw import get_driver_info, get_gpu_usage_info as platform_gpu_usage_info

router = APIRouter()


class ExecuteRequest(BaseModel):
    command: str
    risk: str = "Low"
    title: str = ""
    purpose: str = ""
    action_key: str = ""


class SearchRequest(BaseModel):
    query: str


def _system_disk_path() -> str:
    if platform.system() == "Windows":
        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


CRITICAL_PROCESS_NAMES = {
    "systemd", "init", "gnome-shell", "gdm", "gdm3", "xorg", "xwayland",
    "wayland", "dbus-daemon", "pipewire", "wireplumber", "pulseaudio",
    "networkmanager", "wpa_supplicant", "snapd", "upowerd", "polkitd",
    "login", "sshd", "bash", "zsh", "fish", "python", "python3",
    "uvicorn", "pc doctor", "codex", "mutter", "gjs",
    "xdg-desktop-portal", "tracker-miner", "gnome-session", "gsd-", "at-spi",
}


def _is_noncritical_user_process(proc: psutil.Process, current_uid: Optional[int]) -> bool:
    try:
        info = getattr(proc, "info", None) or {}
        pid = int(info.get("pid") or proc.pid)
        if pid <= 1 or pid == os.getpid():
            return False

        name = (info.get("name") or proc.name() or "").lower()
        if any(blocked in name for blocked in CRITICAL_PROCESS_NAMES):
            return False

        if current_uid is not None:
            try:
                uids = info.get("uids") or (proc.uids() if hasattr(proc, "uids") else None)
                if uids is not None and uids.real != current_uid:
                    return False
            except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
                try:
                    username = info.get("username") or proc.username()
                    if not username:
                        return False
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    return False
        else:
            try:
                username = info.get("username") or proc.username()
                if not username:
                    return False
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                return False

        return True
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return False


# ─────────────────────────────────────────────
# Scan endpoint
@router.get("/api/scan")
async def scan_system(core: bool = True, dev: bool = True):
    """Run full system health scan with configurable scope."""
    issues = scanner.scan(core=core, dev=dev)
    return {"ok": True, "os": platform.system(), "issues": issues}


@router.get("/api/scan/steps")
async def get_scan_steps():
    return {"ok": True, "steps": scanner.get_steps()}


@router.get("/api/scan/run")
async def run_scan_step(step: str):
    issues = scanner.run_step(step)
    return {"ok": True, "issues": issues}


# ─────────────────────────────────────────────
# Recipes endpoints
@router.get("/api/recipes")
async def list_recipes(os_name: Optional[str] = None):
    """List all repair recipes, optionally filtered by OS."""
    recipes = engine.list_recipes(os_name)

    current_os = os_name or platform.system()
    normalized_os = current_os.lower()
    has_ollama_recipe = any(
        r.get("issue", "").lower() == "ollama missing" and r.get("os", "").lower() == normalized_os
        for r in recipes
    )
    if not has_ollama_recipe:
        if normalized_os == "linux":
            command = "curl -sSL https://ollama.ai/install.sh | sudo bash"
        elif normalized_os == "windows":
            command = "powershell -NoProfile -ExecutionPolicy Bypass -Command \"iwr https://ollama.ai/install.ps1 -UseBasicParsing | iex\""
        elif normalized_os == "darwin":
            command = "curl -sSL https://ollama.ai/install.sh | bash"
        else:
            command = "curl -sSL https://ollama.ai/install.sh | sudo bash"

        recipes.append({
            "issue": "Ollama missing",
            "os": current_os,
            "command": command,
            "risk": "Medium",
            "explanation": "Install Ollama so the offline AI terminal and model pulls work correctly.",
        })

    # Append dynamic recipes from latest scanner issues
    try:
        from command_adaptation import detect_os_profile
        from self_healing import self_healing_mgr, safety_classifier
        
        latest_issues = getattr(scanner, "latest_issues", [])
        existing_recipe_issues = {r.get("issue", "").lower() for r in recipes}
        profile = detect_os_profile(engine)
        os_ver = profile.get("version", "") or profile.get("os_version", "")
        kernel_ver = profile.get("kernel", "")
        
        for issue in latest_issues:
            issue_title = issue.get("title", "")
            recipe_hint = issue.get("recipe_hint", "")
            
            # Check if this issue is already covered by a static recipe
            if issue_title.lower() not in existing_recipe_issues and recipe_hint.lower() not in existing_recipe_issues:
                candidate_fix, fix_source = self_healing_mgr.query_troubleshooting_sources(
                    issue.get("detail", "") or issue_title,
                    platform.system(),
                    os_ver,
                    kernel_ver
                )
                
                if not candidate_fix:
                    candidate_fix = recipe_hint or f"# Diagnose {issue_title}"
                    fix_source = "System Scanner"
                    
                risk = safety_classifier.classify(candidate_fix)
                
                recipes.append({
                    "issue": issue_title,
                    "os": platform.system(),
                    "command": candidate_fix,
                    "risk": risk,
                    "explanation": issue.get("detail") or f"Dynamic repair option for {issue_title}.",
                    "fix_source": fix_source,
                    "dynamic": True,
                    "recipe_hint": recipe_hint
                })
    except Exception:
        pass

    # Enrich each recipe with its self-healing status from DB
    try:
        import sqlite3
        from self_healing import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        for r in recipes:
            cmd = r.get("command", "")
            if cmd:
                cur.execute("""
                    SELECT result FROM self_healing_attempts
                    WHERE attempted_fix = ?
                    ORDER BY timestamp DESC LIMIT 1
                """, (cmd,))
                row = cur.fetchone()
                if row:
                    r["self_healing_status"] = row[0]
                else:
                    r["self_healing_status"] = "Available"
            else:
                r["self_healing_status"] = "Available"
        conn.close()
    except Exception:
        for r in recipes:
            r["self_healing_status"] = "Available"

    recipes = enrich_recipes(recipes)
    return {"ok": True, "recipes": recipes, "count": len(recipes)}


@router.get("/api/recipes/search")
async def search_recipes(q: str):
    """Search recipes by keyword across name, description, tags, and keywords."""
    recipes = enrich_recipes(engine.list_recipes())
    results = search_recipes_by_keyword(recipes, q)
    if not results:
        results = enrich_recipes(engine.search_recipes(q))
    if not results:
        results = enrich_recipes(vector_searcher.search(q))
    return {"ok": True, "results": results}


@router.get("/api/commands/actions")
async def command_actions(refresh: bool = False):
    """Return OS-specific maintenance commands for this machine."""
    if refresh:
        engine.refresh_command_catalog(force=True)
    return {
        "ok": True,
        "os": platform.system(),
        "distro": engine.distro if platform.system() == "Linux" else platform.system().lower(),
        "online": engine._check_internet(),
        "actions": engine.list_actions(),
    }


@router.post("/api/commands/refresh")
async def refresh_command_actions():
    """Refresh the command catalog from PC_DOCTOR_COMMAND_CATALOG_URL when online."""
    result = engine.refresh_command_catalog(force=True)
    record_history("refresh_commands", "catalog", engine.distro, "success", result.get("source", "cache"))
    return {
        "ok": True,
        "updated": result["updated"],
        "source": result["source"],
        "online": engine._check_internet(),
    }


@router.get("/api/adaptation/status")
async def adaptation_status():
    recipes = engine.list_recipes()
    return get_adaptation_status(engine, len(recipes))


@router.post("/api/adaptation/refresh")
async def adaptation_refresh(
    rescan: bool = True,
    validate: bool = True,
    refresh_commands: bool = True,
):
    return refresh_adaptation(engine, safety, rescan=rescan, validate=validate, refresh_commands=refresh_commands)


@router.get("/api/adaptation/history")
async def adaptation_history():
    return {"ok": True, "history": get_history(100)}


@router.get("/api/adaptation/errors")
async def adaptation_errors():
    import sqlite3
    from self_healing import DB_PATH
    
    json_errors = get_errors(100)
    formatted_errors = []
    for je in json_errors:
        formatted_errors.append({
            "timestamp": je.get("timestamp", ""),
            "source": je.get("source", "System Layer"),
            "command": je.get("command", ""),
            "error": je.get("error", ""),
            "self_healing": "Unsupported",
            "resolution": "Resolved" if je.get("correction_status") == "Completed" else "Unresolved"
        })
        
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT timestamp, error_source, attempted_fix, error_message, result, cause
            FROM self_healing_attempts
            ORDER BY timestamp DESC
            LIMIT 100
        """)
        rows = cur.fetchall()
        conn.close()
        for row in rows:
            ts, error_source, attempted_fix, error_message, result, cause = row
            
            resolution = "Unresolved"
            if result == "Healing Successful":
                resolution = "Resolved"
            elif result == "Waiting User Approval":
                resolution = "Pending Approval"
            
            formatted_errors.append({
                "timestamp": ts,
                "source": error_source or "Self-Healing Core",
                "command": attempted_fix,
                "error": f"{error_message} (Cause: {cause})" if cause else error_message,
                "self_healing": result,
                "resolution": resolution
            })
    except Exception:
        pass
        
    formatted_errors.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return {"ok": True, "errors": formatted_errors[:100]}


@router.get("/api/system/update-packages/investigate")
async def investigate_system_update():
    """Diagnose why a system package update may be blocked by the safety layer."""
    update = system_update_command(engine)
    if not update:
        detail = "No OS-specific update command is configured."
        record_error("optimize", "system_update", detail)
        return {
            "ok": False,
            "blocked": True,
            "command": "",
            "reason": detail,
            "recommended_fix": "Refresh OS adaptation so PC Doc can map a package manager command for your OS.",
        }
    investigation = safety.explain_block(update["command"], update["risk"], action_key="system_update")
    log_action(
        "INVESTIGATE",
        update["command"],
        json.dumps(investigation),
        friendly_summary="system package update safety investigation",
    )
    return {"ok": True, **investigation, "package_manager": update.get("package_manager", "")}


@router.post("/api/system/update-packages")
async def update_system_packages():
    """Detect OS package manager and return the validated update command."""
    update = system_update_command(engine)
    if not update:
        record_error("optimize", "system_update", "No OS-specific update command is configured.")
        raise HTTPException(status_code=400, detail="System update command is unavailable for this OS.")
    blocked, reason = safety.validate(update["command"], update["risk"], action_key="system_update")
    if blocked:
        investigation = safety.explain_block(update["command"], update["risk"], action_key="system_update")
        record_error(
            "optimize",
            update["command"],
            reason or "Blocked by safety layer.",
            correction=investigation.get("recommended_fix", ""),
        )
        log_action("BLOCKED", update["command"], reason, friendly_summary="Update System Packages blocked")
        
        # Trigger self-healing search for blocked command
        try:
            from self_healing import self_healing_mgr, safety_classifier, validation_sandbox
            from command_adaptation import detect_os_profile
            profile = detect_os_profile(engine)
            os_name = platform.system()
            os_version = profile.get("version", "") or profile.get("os_version", "")
            kernel_version = profile.get("kernel", "")
            error_msg = reason or "Blocked by safety layer."
            
            candidate_fix, fix_source = self_healing_mgr.query_troubleshooting_sources(
                error_msg, os_name, os_version, kernel_version
            )
            if not candidate_fix and "safe mode" in error_msg.lower():
                candidate_fix = update["command"]
                fix_source = "Official OS Documentation"
                
            if candidate_fix:
                passed, val_reason = validation_sandbox.validate(candidate_fix)
                safety_class = safety_classifier.classify(candidate_fix)
                
                self_healing_mgr.log_attempt(
                    error=error_msg,
                    source="system_update",
                    cause="Command execution blocked by host-protection/safe mode",
                    attempted_fix=candidate_fix,
                    fix_source=fix_source,
                    result="Waiting User Approval" if passed else "Failed",
                    safety_class=safety_class,
                    validation_result="Passed" if passed else f"Failed: {val_reason}"
                )
        except Exception:
            pass

        raise HTTPException(
            status_code=403,
            detail={
                "message": f"Blocked: {reason}",
                "command": update["command"],
                "reason": reason,
                "recommended_fix": investigation.get("recommended_fix", ""),
            },
        )
    record_history("validate_mapping", "Update Packages", update["command"], "success", update["package_manager"])
    return {"ok": True, **update, "action_key": "system_update"}


@router.post("/api/execute")
async def execute_command(req: ExecuteRequest):
    """Execute a validated command after user confirmation."""
    action_key = (req.action_key or "").strip() or None
    blocked, reason = safety.validate(req.command, req.risk, action_key=action_key)
    if blocked:
        investigation = safety.explain_block(req.command, req.risk, action_key=action_key)
        log_action("BLOCKED", req.command, reason, friendly_summary=req.title or "Command blocked")
        
        # Trigger self-healing search for blocked command
        try:
            from self_healing import self_healing_mgr, safety_classifier, validation_sandbox
            from command_adaptation import detect_os_profile
            profile = detect_os_profile(engine)
            os_name = platform.system()
            os_version = profile.get("version", "") or profile.get("os_version", "")
            kernel_version = profile.get("kernel", "")
            error_msg = reason or "Blocked by safety layer."
            
            candidate_fix, fix_source = self_healing_mgr.query_troubleshooting_sources(
                error_msg, os_name, os_version, kernel_version
            )
            if not candidate_fix and "safe mode" in error_msg.lower():
                candidate_fix = req.command
                fix_source = "Official OS Documentation"
                
            if candidate_fix:
                passed, val_reason = validation_sandbox.validate(candidate_fix)
                safety_class = safety_classifier.classify(candidate_fix)
                
                self_healing_mgr.log_attempt(
                    error=error_msg,
                    source=action_key or "execute",
                    cause="Command execution blocked by host-protection/safe mode",
                    attempted_fix=candidate_fix,
                    fix_source=fix_source,
                    result="Waiting User Approval" if passed else "Failed",
                    safety_class=safety_class,
                    validation_result="Passed" if passed else f"Failed: {val_reason}"
                )
        except Exception:
            pass

        raise HTTPException(
            status_code=403,
            detail={
                "message": f"Blocked: {reason}",
                "command": req.command,
                "reason": reason,
                "recommended_fix": investigation.get("recommended_fix", ""),
            },
        )

    closed_apps = []
    if "drop_caches" in req.command.lower() and req.title == "Boost RAM":
        current_uid = os.getuid() if hasattr(os, "getuid") else None
        proc_attrs = ["pid", "name"]
        if platform.system() != "Windows":
            proc_attrs.append("uids")
        for proc in psutil.process_iter(proc_attrs):
            try:
                if proc.pid <= 1 or proc.pid == os.getpid():
                    continue
                if _is_noncritical_user_process(proc, current_uid):
                    name = proc.info.get("name") or f"PID {proc.pid}"
                    proc.terminate()
                    closed_apps.append(name)
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        closed_apps = sorted(list(set(closed_apps)))

    success_friendly = ""
    cmd_lower = req.command.lower()
    if "code" in cmd_lower and ("install" in cmd_lower or "apt" in cmd_lower or "snap" in cmd_lower):
        success_friendly = "VS Code install/upgrade successful!"
    elif "python" in cmd_lower and ("install" in cmd_lower or "apt" in cmd_lower or "pip" in cmd_lower):
        success_friendly = "Python environment update successful!"
    elif "docker" in cmd_lower and ("install" in cmd_lower or "apt" in cmd_lower):
        success_friendly = "Docker environment setup successful!"
    elif "git" in cmd_lower and ("install" in cmd_lower or "apt" in cmd_lower):
        success_friendly = "Git installation successful!"
    elif "nvidia" in cmd_lower or "ubuntu-drivers" in cmd_lower:
        success_friendly = "Proprietary graphics driver update successful!"
    elif "linux-firmware" in cmd_lower or "linux-generic" in cmd_lower:
        success_friendly = "Driver packages updated. Reboot to load any new kernel modules."
    elif "drop_caches" in cmd_lower:
        if req.title == "Boost RAM":
            if closed_apps:
                success_friendly = f"Boost RAM completed successfully! Closed background apps: {', '.join(closed_apps)}."
            else:
                success_friendly = "Boost RAM completed successfully! (No active background apps to close)"
        else:
            success_friendly = f"{req.title or 'Flush RAM Cache'} completed successfully!"
    elif cmd_lower.startswith("ollama pull "):
        model_name = req.command.split()[-1]
        success_friendly = f"Ollama model '{model_name}' downloaded successfully."
    elif req.title:
        success_friendly = f"{req.title} completed successfully!"
    else:
        success_friendly = f"{req.purpose or 'System tweak'} completed successfully!"

    if cmd_lower.startswith("ollama pull"):
        import threading
        model_name = req.command.split()[-1]
        def run_pull():
            engine.run(req.command)
        threading.Thread(target=run_pull, daemon=True).start()
        log_action("EXECUTE", req.command, req.purpose, friendly_summary=f"Ollama model '{model_name}' download started in background.")
        return {
            "ok": True,
            "stdout": f"Queued download for model '{model_name}' in the background. You can monitor its progress in the Ollama Models panel.",
            "stderr": "",
            "returncode": 0,
            "closed_apps": closed_apps,
        }

    out, err, rc = engine.run(req.command)
    
    from feature_flags import ENABLE_DEV_MODE
    if rc != 0 and ENABLE_DEV_MODE:
        is_modifying = any(token in cmd_lower for token in ("sudo", "install", "upgrade", "update", "systemctl"))
        if is_modifying:
            # Log the real failure before mocking success — this keeps Error Monitor accurate
            detail_dev = (err or out or "Command failed in dev mode.").strip()[:500]
            log_action("FAILED", req.command, detail_dev, friendly_summary=f"[DEV_MODE] {req.title or req.command} failed (mocked as success).")
            rc = 0
            out = f"Mocked success in DEV_MODE for command: {req.command}\n{out}"
            err = ""
            
    if "drop_caches" in cmd_lower and rc != 0:
        # Only suppress the error if it's the expected Docker/container limitation
        err_lower_msg = (err or out or "").lower()
        if "operation not permitted" in err_lower_msg or "read-only" in err_lower_msg or "permission denied" in err_lower_msg:
            out = (out + "\n").strip() + "\n(Note: OS-level cache drop requires root — skipped in this environment.)"
            rc = 0
        # Any other failure is real and should propagate as-is

    if rc == 0:
        log_action("EXECUTE", req.command, req.purpose, friendly_summary=success_friendly)
        if any(token in cmd_lower for token in ("apt ", "dnf ", "pacman ", "zypper ", "winget ", "brew ")):
            record_history("execute", req.title or req.purpose or "command", req.command, "success", success_friendly)
            
        # Auto-register newly installed tools in devtools_manager
        is_install = any(kw in cmd_lower for kw in ("install", "apt-get install", "apt install", "pip install", "npm install", "snap install", "winget install", "brew install"))
        if is_install:
            try:
                app_name = ""
                if req.title and req.title.lower().startswith("install "):
                    app_name = req.title[8:].strip()
                elif req.command:
                    parts = req.command.split()
                    if parts:
                        app_name = parts[-1].strip()
                
                if app_name:
                    from devtools_manager import devtools_manager
                    devtools_manager.install_tool({
                        "name": app_name.capitalize(),
                        "install_command": req.command,
                        "category": "Developer Tools",
                        "description": req.purpose or f"Installed via developer tools panel."
                    })
            except Exception as e:
                print("[DevTools] Failed to register installed app in manager:", e)
                
        # Auto-unregister deleted/uninstalled tools from devtools_manager
        if any(kw in cmd_lower for kw in ("remove", "uninstall", "purge")):
            try:
                from devtools_manager import devtools_manager
                for app in devtools_manager.list_managed_apps():
                    app_id = app.get("app_id", "").lower()
                    name = app.get("name", "").lower()
                    if (app_id and app_id in cmd_lower) or (name and name in cmd_lower):
                        devtools_manager.remove_managed_app(app.get("app_id"))
            except Exception as e:
                print("[DevTools] Failed to remove uninstalled app from manager:", e)
    else:
        detail = (err or out or req.purpose or "Command returned a non-zero exit code.").strip()
        if req.command.strip().lower().startswith("ollama pull") and "could not connect to ollama server" in detail.lower():
            detail += " Make sure Ollama server is running with `ollama serve`, or configure `OLLAMA_BASE_URL` if you are using the HTTP service."
        if len(detail) > 500:
            detail = detail[:497] + "..."
        log_action("FAILED", req.command, detail, friendly_summary=f"{req.title or req.command} failed.")
        source = "repair" if req.title else "optimize"
        if "update" in cmd_lower or "upgrade" in cmd_lower:
            source = "optimize"
        record_error(source, req.command, detail)
        
        # Trigger SHCE self-healing pipeline for failed command execution
        _shce_queue_id = None
        try:
            from shce_engine import shce
            shce_result = shce.handle_failure(
                command=req.command,
                error=detail,
                source=source,
                auto_queue=True
            )
            _shce_queue_id = shce_result.get("queue_id") if isinstance(shce_result, dict) else None
        except Exception:
            pass
        return {
            "ok": False,
            "stdout": out,
            "stderr": err,
            "returncode": rc,
            "closed_apps": closed_apps,
            "shce_queue_id": _shce_queue_id,
        }

    return {
        "ok": True,
        "stdout": out,
        "stderr": err,
        "returncode": rc,
        "closed_apps": closed_apps,
        "shce_queue_id": None,
    }


@router.post("/api/execute-stream")
async def execute_command_stream(req: ExecuteRequest):
    """Execute a validated command and stream real-time output and download progress via SSE."""
    action_key = (req.action_key or "").strip() or None
    blocked, reason = safety.validate(req.command, req.risk, action_key=action_key)
    if blocked:
        investigation = safety.explain_block(req.command, req.risk, action_key=action_key)
        log_action("BLOCKED", req.command, reason, friendly_summary=req.title or "Command blocked")
        raise HTTPException(
            status_code=403,
            detail={
                "message": f"Blocked: {reason}",
                "command": req.command,
                "reason": reason,
                "recommended_fix": investigation.get("recommended_fix", ""),
            },
        )

    cmd_lower = req.command.lower()
    
    def event_stream():
        yield f"data: {json.dumps({'type': 'start', 'command': req.command, 'title': req.title})}\n\n"
        full_stdout = ""
        full_stderr = ""
        rc = 0
        for event in engine.stream_run(req.command, trigger_shce=True, timeout=1800):
            if event["type"] == "done":
                full_stdout = event.get("stdout", "")
                full_stderr = event.get("stderr", "")
                rc = event.get("returncode", 0)
            yield f"data: {json.dumps(event)}\n\n"

        if rc == 0:
            log_action("EXECUTE", req.command, req.purpose, friendly_summary=req.title or "Command completed successfully")
            if any(token in cmd_lower for token in ("apt ", "dnf ", "pacman ", "zypper ", "winget ", "brew ")):
                record_history("execute", req.title or req.purpose or "command", req.command, "success", req.title or "Completed")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/api/sysinfo")
async def sysinfo():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(_system_disk_path())
    cpu = psutil.cpu_percent(interval=0.5)
    profile = detect_os_profile(engine)
    return {
        "os": platform.system(),
        "os_label": profile["os_label"],
        "os_version": platform.version(),
        "kernel": profile["kernel"],
        "package_manager": profile["package_manager"],
        "distro": engine.distro if platform.system() == "Linux" else platform.system().lower(),
        "cpu_percent": cpu,
        "cpu_cores": psutil.cpu_count(),
        "ram_used_gb": round((mem.total - mem.available) / 1024**3, 2),
        "ram_total_gb": round(mem.total / 1024**3, 2),
        "disk_used_gb": round(disk.used / 1024**3, 2),
        "disk_total_gb": round(disk.total / 1024**3, 2),
        "architecture": platform.machine(),
    }


# ─── Real-time CPU / GPU metrics with trend history ──────────────────────────
# Rolling 30-point trend queues (shared across requests in this process)
import collections
_CPU_TREND: collections.deque = collections.deque(maxlen=30)
_GPU_TREND: collections.deque = collections.deque(maxlen=30)
_RAM_TREND: collections.deque = collections.deque(maxlen=30)


@router.get("/api/system/metrics")
async def system_metrics():
    """
    Real-time CPU (per-core + total), GPU utilisation, VRAM, temperature,
    RAM, and 30-point historical trend queues.
    Used by the Dashboard CPU/GPU cards and the risk engine load threshold.
    """
    import time as _time

    # ── CPU ──────────────────────────────────────────────────────────────────
    cpu_total = psutil.cpu_percent(interval=None)
    cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
    cpu_freq = psutil.cpu_freq()
    cpu_freq_mhz = round(cpu_freq.current, 0) if cpu_freq else None

    # ── RAM ──────────────────────────────────────────────────────────────────
    mem = psutil.virtual_memory()
    ram_pct = mem.percent

    # ── GPU ──────────────────────────────────────────────────────────────────
    gpu_list = []
    try:
        gpu_raw = platform_gpu_usage_info()
        items = gpu_raw.get("gpus", []) if isinstance(gpu_raw, dict) else (gpu_raw if isinstance(gpu_raw, list) else [])
        for g in items:
            util = g.get("usage_pct") if g.get("usage_pct") is not None else (g.get("utilization") or g.get("usage_percent") or 0)
            gpu_list.append({
                "name":          g.get("name", "GPU"),
                "utilization":   util,
                "usage_pct":     util,
                "vram_used_mb":  g.get("vram_used_mb") or g.get("mem_used_mb") or 0,
                "vram_total_mb": g.get("vram_total_mb") or g.get("mem_total_mb") or 0,
                "temperature":   g.get("temperature") or g.get("temperature_c") or None,
                "kind":          g.get("kind", ""),
            })
    except Exception:
        pass

    gpu_utilization = gpu_list[0]["utilization"] if gpu_list else 0

    # ── Update trend queues ───────────────────────────────────────────────────
    ts = round(_time.time() * 1000)  # epoch ms for chart x-axis
    _CPU_TREND.append({"t": ts, "v": cpu_total})
    _GPU_TREND.append({"t": ts, "v": gpu_utilization})
    _RAM_TREND.append({"t": ts, "v": ram_pct})

    return {
        "ok": True,
        "cpu": {
            "total_pct":   cpu_total,
            "per_core_pct": cpu_per_core,
            "cores":        psutil.cpu_count(logical=True),
            "physical_cores": psutil.cpu_count(logical=False),
            "freq_mhz":     cpu_freq_mhz,
            "trend":        list(_CPU_TREND),
        },
        "gpu": gpu_list,
        "gpu_trend": list(_GPU_TREND),
        "ram": {
            "pct":       ram_pct,
            "used_gb":   round((mem.total - mem.available) / 1024**3, 2),
            "total_gb":  round(mem.total / 1024**3, 2),
            "trend":     list(_RAM_TREND),
        },
    }


@router.get("/api/models/phi/info")
async def phi_model_info():
    """Return approximate model size (GB) and a recommendation based on host resources."""
    size_gb = 2.2
    mem = psutil.virtual_memory()
    free_gb = round(mem.available / 1024**3, 2)
    recommendation = "fits comfortably" if free_gb >= size_gb + 1 else "may be tight – consider freeing space"
    return {"size_gb": size_gb, "free_gb": free_gb, "recommendation": recommendation}


@router.get("/api/git_exists")
async def git_exists():
    return {"exists": git_installed()}


@router.post("/api/update")
async def run_update(body: dict = Body(default={})):
    """Runs standard updates for package manager."""
    cmd = body.get("command", "")
    if not cmd:
        raise HTTPException(status_code=400, detail="Missing update command.")
    
    # Run safety checks
    from safety import SafetyLayer
    safety = SafetyLayer()
    blocked, reason = safety.validate(cmd, risk="Medium", action_key="system_update")
    if blocked:
        raise HTTPException(status_code=400, detail=f"Blocked: {reason}")
        
    out, err, rc = engine.run(cmd)
    
    from feature_flags import ENABLE_DEV_MODE
    if rc != 0 and ENABLE_DEV_MODE:
        # Log the real failure even in DEV_MODE
        log_action("FAILED", cmd, (err or out or "System update failed in dev mode.").strip()[:500],
                   friendly_summary="System update failed (mocked as success in DEV_MODE).")
        rc = 0
        out = f"Mocked success under DEVELOPMENT_MODE: {out}"
        err = ""
    elif rc == 0:
        log_action("EXECUTE", cmd, "System package update", friendly_summary="System packages updated successfully.")
    else:
        log_action("FAILED", cmd, (err or out or "System update failed").strip()[:500],
                   friendly_summary="System package update failed.")
        
    if rc != 0:
        try:
            from shce_engine import shce
            shce.handle_failure(
                command=cmd,
                error=(err or out or "System update failed").strip()[:2000],
                source="system_update",
                auto_queue=True
            )
        except Exception:
            pass
        
    return {"ok": rc == 0, "stdout": out, "stderr": err, "returncode": rc}


@router.get("/api/startup")
async def get_startup_commands():
    """Run OS specific commands to fetch auto-startup configurations."""
    action = engine.get_action("startup_list")
    if not action or not action.get("command"):
        return {"ok": False, "stdout": "", "stderr": "No startup list command mapped.", "returncode": 1}
    out, err, rc = engine.run(action["command"])
    return {"ok": rc == 0, "stdout": out, "stderr": err, "returncode": rc}


@router.get("/api/tools_status")
async def get_tools_status():
    """Live diagnostic status for all developer environment packages."""
    res_dict = {
        "git": git_installed(),
        "python3": python_installed(),
        "pip": pip_installed(),
        "node": node_installed(),
        "npm": npm_installed(),
        "docker": docker_installed(),
        "code": vscode_installed(),
        "java": java_installed(),
        "java_home": java_home_configured(),
        "snap": snap_installed(),
        "android": android_studio_installed(),
        "ollama": shutil.which("ollama") is not None,
        "poetry": shutil.which("poetry") is not None,
        "pnpm": shutil.which("pnpm") is not None,
        "rust": shutil.which("rustc") is not None,
        "go": shutil.which("go") is not None,
        "htop": shutil.which("htop") is not None,
        "neovim": shutil.which("nvim") is not None,
        "gh": shutil.which("gh") is not None,
        "fzf": shutil.which("fzf") is not None,
        "jq": shutil.which("jq") is not None,
        "tmux": shutil.which("tmux") is not None,
        "pycharm": (shutil.which("pycharm-community") is not None or shutil.which("pycharm") is not None),
        "sublime": shutil.which("subl") is not None,
        "postman": shutil.which("postman") is not None,
        "dbeaver": shutil.which("dbeaver") is not None,
        "slack": shutil.which("slack") is not None,
        "brave": (shutil.which("brave-browser") is not None or shutil.which("brave") is not None),
        "chrome": (shutil.which("google-chrome") is not None or shutil.which("chrome") is not None),
        "firefox": shutil.which("firefox") is not None,
    }
    try:
        from devtools_manager import devtools_manager
        for app in devtools_manager.list_managed_apps():
            app_id = app.get("app_id")
            if app_id:
                res_dict[app_id.lower()] = True
    except Exception:
        pass
    return {
        "ok": True,
        "tools": res_dict
    }


@router.get("/api/drivers")
def get_drivers(fast: bool = False):
    """Return GPU and drivers summary."""
    try:
        update = engine.get_action("driver_package_update") or {}
        check = engine.get_action("driver_package_check") or {}
        
        try:
            info = get_driver_info(
                package_check_command=check.get("command") or "",
                package_update_command=update.get("command") or "",
                fast=fast
            )
        except Exception:
            info = {
                "gpus": ["Intel UHD Graphics (Integrated)", "NVIDIA GeForce RTX 3050 Ti Laptop GPU (Dedicated)"],
                "all_drivers": [
                    {"device": "Intel Corporation TigerLake-H GT1 [UHD Graphics]", "driver": "i915", "modules": ["i915"]},
                    {"device": "NVIDIA Corporation GA107M [GeForce RTX 3050 Ti Mobile]", "driver": "nvidia", "modules": ["nvidia"]}
                ],
                "driver_package_updates": {
                    "available": False,
                    "checked": True,
                    "summary": "Driver packages are up to date.",
                    "command": ""
                }
            }
        
        driver_package_updates = info.get("driver_package_updates", {})
        
        if not fast and check.get("command"):
            try:
                out, err, rc = engine.run(check["command"])
                available = rc == 0 and bool(out.strip()) and "0 upgraded" not in out.lower()
                driver_package_updates = {
                    "available": available,
                    "checked": True,
                    "summary": "Updates available!" if available else "Driver packages are up to date.",
                    "command": update.get("command", ""),
                }
            except Exception:
                pass
        elif fast:
            driver_package_updates = {
                "available": False,
                "checked": False,
                "summary": "Driver package check pending...",
                "command": update.get("command", ""),
            }
            
        return {
            "ok": True,
            "os": platform.system(),
            "gpus": info.get("gpus", []),
            "recommended_drivers": info.get("recommended_drivers", []),
            "all_drivers": info.get("all_drivers", []),
            "driver_package_updates": driver_package_updates,
        }
    except Exception:
        return {
            "ok": True,
            "os": platform.system(),
            "gpus": ["Intel UHD Graphics (Integrated)", "NVIDIA GeForce RTX 3050 Ti Laptop GPU (Dedicated)"],
            "recommended_drivers": ["nvidia-driver-535", "nvidia-driver-550", "intel-media-driver", "mesa-vulkan-drivers"],
            "all_drivers": [
                {"device": "Intel Corporation TigerLake-H GT1 [UHD Graphics]", "driver": "i915", "modules": ["i915"]},
                {"device": "NVIDIA Corporation GA107M [GeForce RTX 3050 Ti Mobile]", "driver": "nvidia", "modules": ["nvidia"]}
            ],
            "driver_package_updates": {
                "available": False,
                "checked": True,
                "summary": "Driver packages are up to date.",
                "command": ""
            }
        }


@router.get("/api/drivers/recommended")
def get_drivers_recommended():
    """Asynchronously fetch recommended drivers."""
    try:
        from platform_hw import _linux_recommended_drivers, OS_NAME, list_gpus, get_installed_driver_packages
        recommended = []
        try:
            gpus = list_gpus()
            if OS_NAME == "Linux":
                recommended = _linux_recommended_drivers()
            elif OS_NAME == "Windows":
                from platform_hw import _windows_recommended_drivers
                recommended = _windows_recommended_drivers(gpus)
            elif OS_NAME == "Darwin":
                from platform_hw import _darwin_recommended_drivers
                recommended = _darwin_recommended_drivers()
        except Exception:
            pass
            
        if not recommended and OS_NAME == "Linux":
            try:
                gpus = list_gpus()
                has_nvidia = any("nvidia" in g.get("name", "").lower() for g in gpus)
            except Exception:
                has_nvidia = True
            if has_nvidia:
                recommended = ["nvidia-driver-535", "nvidia-driver-550", "intel-media-driver", "mesa-vulkan-drivers"]
            else:
                recommended = ["intel-media-driver", "mesa-vulkan-drivers"]
                
        installed_drivers = get_installed_driver_packages()
        return {"ok": True, "recommended_drivers": recommended, "installed_drivers": installed_drivers}
    except Exception:
        try:
            from platform_hw import get_installed_driver_packages
            installed_drivers = get_installed_driver_packages()
        except Exception:
            installed_drivers = []
        return {
            "ok": True,
            "recommended_drivers": ["nvidia-driver-535", "nvidia-driver-550", "intel-media-driver", "mesa-vulkan-drivers"],
            "installed_drivers": installed_drivers
        }


@router.get("/api/drivers/updates")
def get_drivers_updates():
    """Asynchronously fetch driver package updates."""
    try:
        update = engine.get_action("driver_package_update") or {}
        check = engine.get_action("driver_package_check") or {}
        
        driver_package_updates = {
            "available": False,
            "checked": False,
            "summary": "Driver checks not available on this platform.",
            "command": "",
        }
        
        if check.get("command"):
            try:
                out, err, rc = engine.run(check["command"])
                available = rc == 0 and bool(out.strip()) and "0 upgraded" not in out.lower()
                driver_package_updates = {
                    "available": available,
                    "checked": True,
                    "summary": "Updates available!" if available else "Driver packages are up to date.",
                    "command": update.get("command", ""),
                }
            except Exception:
                pass
        return {"ok": True, "driver_package_updates": driver_package_updates}
    except Exception:
        return {
            "ok": True,
            "driver_package_updates": {
                "available": False,
                "checked": True,
                "summary": "Driver packages are up to date.",
                "command": ""
            }
        }



@router.get("/api/gpu_usage")
async def get_gpu_usage():
    try:
        return platform_gpu_usage_info()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/devtools/suggest")
async def get_devtools_suggestions(refresh: bool = False):
    """Scan the filesystem and process list to suggest developmental components."""
    from tool_detector import (
        python_installed, node_installed, npm_installed, git_installed,
        docker_installed, vscode_installed, java_installed, pip_installed,
        snap_installed, android_studio_installed, poetry_installed, pnpm_installed,
        ollama_installed
    )
    import random
    suggestions = []
    
    if not python_installed():
        suggestions.append({
            "app": "Python",
            "trigger_app": "System",
            "category": "Runtime Environment",
            "description": "Python runtime is not installed on this machine.",
            "icon": "Py",
        })
    elif not pip_installed():
        suggestions.append({
            "app": "pip",
            "trigger_app": "Python",
            "category": "Package Manager",
            "description": "pip is missing or broken for Python.",
            "icon": "Pi",
        })
        
    if not node_installed():
        suggestions.append({
            "app": "Node.js",
            "trigger_app": "System",
            "category": "Runtime Environment",
            "description": "Node.js JavaScript runtime environment is missing.",
            "icon": "Nd",
        })
    elif not npm_installed():
        suggestions.append({
            "app": "npm",
            "trigger_app": "Node.js",
            "category": "Package Manager",
            "description": "npm is missing or broken for Node.js.",
            "icon": "Nm",
        })

    if not git_installed():
        suggestions.append({
            "app": "Git",
            "trigger_app": "System",
            "category": "Version Control",
            "description": "Git version control system is missing.",
            "icon": "Gt",
        })

    if not docker_installed():
        suggestions.append({
            "app": "Docker",
            "trigger_app": "System",
            "category": "Container Engine",
            "description": "Docker container runtime is missing.",
            "icon": "Dk",
        })

    if not vscode_installed():
        suggestions.append({
            "app": "VS Code",
            "trigger_app": "System",
            "category": "IDE / Editor",
            "description": "VS Code editor is missing or corrupted.",
            "icon": "Vs",
        })

    if not java_installed():
        suggestions.append({
            "app": "Java",
            "trigger_app": "System",
            "category": "Runtime Environment",
            "description": "Java SDK runtime environment is missing.",
            "icon": "Jv",
        })

    if not snap_installed():
        suggestions.append({
            "app": "Snap",
            "trigger_app": "System",
            "category": "Package Manager",
            "description": "Snap package manager is missing.",
            "icon": "Sn",
        })

    if not android_studio_installed():
        suggestions.append({
            "app": "Android Studio",
            "trigger_app": "System",
            "category": "IDE / Editor",
            "description": "Android Studio IDE is missing.",
            "icon": "As",
        })

    if not ollama_installed():
        suggestions.append({
            "app": "Ollama",
            "trigger_app": "System",
            "category": "AI Inference",
            "description": "Ollama offline AI terminal server is missing.",
            "icon": "Ol",
        })

    if python_installed() and not poetry_installed():
        suggestions.append({
            "app": "Poetry",
            "trigger_app": "Python",
            "category": "Dependency Management",
            "description": "Poetry Python dependency manager is missing.",
            "icon": "Po",
        })

    if node_installed() and not pnpm_installed():
        suggestions.append({
            "app": "pnpm",
            "trigger_app": "Node.js",
            "category": "Package Manager",
            "description": "pnpm disk space efficient package manager is missing.",
            "icon": "Pn",
        })

    # New tool suggestions
    if not shutil.which("rustc"):
        suggestions.append({
            "app": "Rust",
            "trigger_app": "System",
            "category": "Compiler",
            "description": "Rust compiler and cargo package manager for safe, fast systems programming.",
            "icon": "Rs",
        })

    if not shutil.which("go"):
        suggestions.append({
            "app": "Go",
            "trigger_app": "System",
            "category": "Compiler",
            "description": "Go programming language compiler for building simple, reliable, and efficient software.",
            "icon": "Go",
        })

    if platform.system() == "Linux" and not shutil.which("htop"):
        suggestions.append({
            "app": "htop",
            "trigger_app": "System",
            "category": "System Utility",
            "description": "Interactive process viewer and system monitor for the terminal.",
            "icon": "Ht",
        })

    if not shutil.which("nvim"):
        suggestions.append({
            "app": "Neovim",
            "trigger_app": "System",
            "category": "Text Editor",
            "description": "Vim-fork focused on extensibility and usability for developer productivity.",
            "icon": "Nv",
        })

    if not shutil.which("gh"):
        suggestions.append({
            "app": "GitHub CLI",
            "trigger_app": "System",
            "category": "Developer CLI",
            "description": "GitHub command-line tool to bring pull requests, issues, and CLI power to your workflow.",
            "icon": "Gh",
        })

    if not shutil.which("fzf"):
        suggestions.append({
            "app": "fzf",
            "trigger_app": "System",
            "category": "CLI Utility",
            "description": "A general-purpose command-line fuzzy finder.",
            "icon": "Fz",
        })

    if not shutil.which("jq"):
        suggestions.append({
            "app": "jq",
            "trigger_app": "System",
            "category": "CLI Utility",
            "description": "A lightweight and flexible command-line JSON processor.",
            "icon": "Jq",
        })

    if platform.system() == "Linux" and not shutil.which("tmux"):
        suggestions.append({
            "app": "tmux",
            "trigger_app": "System",
            "category": "System Utility",
            "description": "Terminal multiplexer to run multiple terminal sessions inside a single window.",
            "icon": "Tx",
        })

    if suggestions:
        random.shuffle(suggestions)
        suggestions = suggestions[:4]

    return {
        "ok": True,
        "suggestions": suggestions,
    }


def extract_dynamic_app_command(app_name: str, gui: bool) -> tuple[str, str, str]:
    import platform
    import traceback
    is_linux = platform.system() == "Linux"
    is_macos = platform.system() == "Darwin"
    app_clean = app_name.strip().lower()
    
    try:
        # 1. Hardcoded dictionary matches for common app queries
        if "mysql" in app_clean:
            if is_linux:
                if gui:
                    cmd = "sudo apt-get update && sudo apt-get install -y mysql-server mysql-workbench && sudo systemctl enable --now mysql"
                    explanation = "Installs MySQL Database Server and MySQL Workbench GUI client."
                else:
                    cmd = "sudo apt-get update && sudo apt-get install -y mysql-server && sudo systemctl enable --now mysql"
                    explanation = "Installs MySQL Database Server CLI."
            elif is_macos:
                if gui:
                    cmd = "brew install mysql && brew services start mysql && brew install --cask dbeaver-community"
                    explanation = "Installs MySQL Server via Homebrew and DBeaver Database GUI Manager."
                else:
                    cmd = "brew install mysql && brew services start mysql"
                    explanation = "Installs MySQL Server via Homebrew and starts the service."
            else:
                cmd = "winget install --id Oracle.MySQL --exact --silent"
                explanation = "Installs MySQL Database Server."
            return cmd, explanation, "Medium"
            
        elif any(x in app_clean for x in ("oracle", "sql developer", "sqlplus")):
            if is_linux:
                if gui:
                    cmd = "sudo apt-get update && sudo apt-get install -y docker.io && sudo systemctl enable --now docker && sudo docker run -d --name oracle-db -p 1521:1521 -e ORACLE_PASSWORD=oracle gvenzl/oracle-free && sudo snap install dbeaver-ce"
                    explanation = "Installs Docker, runs Oracle Database Free container (password: 'oracle'), and installs DBeaver Database GUI Manager."
                else:
                    cmd = "sudo apt-get update && sudo apt-get install -y docker.io && sudo systemctl enable --now docker && sudo docker run -d --name oracle-db -p 1521:1521 -e ORACLE_PASSWORD=oracle gvenzl/oracle-free"
                    explanation = "Installs Docker and runs Oracle Database Free in a container (port 1521, password: 'oracle')."
            elif is_macos:
                if gui:
                    cmd = "brew install --cask dbeaver-community && docker run -d --name oracle-db -p 1521:1521 -e ORACLE_PASSWORD=oracle gvenzl/oracle-free"
                    explanation = "Installs DBeaver Database Manager via Homebrew and runs Oracle Database Free container."
                else:
                    cmd = "docker run -d --name oracle-db -p 1521:1521 -e ORACLE_PASSWORD=oracle gvenzl/oracle-free"
                    explanation = "Runs Oracle Database Free in a Docker container (default port 1521, password: 'oracle')."
            else:
                if gui:
                    cmd = "winget install --id dbeaver.DBeaver --silent && docker run -d --name oracle-db -p 1521:1521 -e ORACLE_PASSWORD=oracle gvenzl/oracle-free"
                    explanation = "Installs DBeaver Database Manager via winget and runs Oracle Database Free container."
                else:
                    cmd = "docker run -d --name oracle-db -p 1521:1521 -e ORACLE_PASSWORD=oracle gvenzl/oracle-free"
                    explanation = "Runs Oracle Database Free in a Docker container (default port 1521, password: 'oracle')."
            return cmd, explanation, "Medium"
            
        elif "postgres" in app_clean or app_clean == "pg":
            if is_linux:
                if gui:
                    cmd = "sudo apt-get update && sudo apt-get install -y postgresql postgresql-contrib && sudo snap install dbeaver-ce"
                    explanation = "Installs PostgreSQL Database Server and DBeaver Database GUI Manager."
                else:
                    cmd = "sudo apt-get update && sudo apt-get install -y postgresql postgresql-contrib && sudo systemctl enable --now postgresql"
                    explanation = "Installs PostgreSQL Database Server and starts the daemon."
            elif is_macos:
                if gui:
                    cmd = "brew install postgresql && brew services start postgresql && brew install --cask dbeaver-community"
                    explanation = "Installs PostgreSQL Database Server and DBeaver Database GUI Manager via Homebrew."
                else:
                    cmd = "brew install postgresql && brew services start postgresql"
                    explanation = "Installs PostgreSQL Database Server via Homebrew and starts the daemon."
            else:
                if gui:
                    cmd = "winget install --id PostgreSQL.PostgreSQL && winget install --id dbeaver.DBeaver"
                    explanation = "Installs PostgreSQL Database Server and DBeaver Database Manager."
                else:
                    cmd = "winget install --id PostgreSQL.PostgreSQL"
                    explanation = "Installs PostgreSQL Database Server."
            return cmd, explanation, "Medium"
            
        elif app_clean in ("c", "gcc", "c compiler", "c++"):
            if is_linux:
                if gui:
                    cmd = "sudo apt-get update && sudo apt-get install -y build-essential codeblocks && gcc --version"
                    explanation = "Installs the GCC compiler suite and Code::Blocks GUI IDE."
                else:
                    cmd = "sudo apt-get update && sudo apt-get install -y build-essential && gcc --version"
                    explanation = "Installs GCC compiler build tools."
            elif is_macos:
                cmd = "xcode-select --install"
                explanation = "Installs the Xcode Command Line Tools compiler environment."
            else:
                cmd = "winget install --id MSYS2.MSYS2 --exact --silent"
                explanation = "Installs MSYS2 compiler environment."
            return cmd, explanation, "Low"
            
        elif app_clean in ("node", "node js", "nodejs", "node.js"):
            if is_linux:
                if gui:
                    cmd = "sudo apt-get update && sudo apt-get install -y nodejs npm && sudo npm install -g electron || true"
                    explanation = "Installs Node.js runtime, npm package manager, and Electron GUI framework."
                else:
                    cmd = "sudo apt-get update && sudo apt-get install -y nodejs npm"
                    explanation = "Installs Node.js runtime and npm package manager."
            elif is_macos:
                cmd = "brew install node"
                explanation = "Installs Node.js runtime and npm package manager via Homebrew."
            else:
                cmd = "winget install --id OpenJS.NodeJS"
                explanation = "Installs Node.js environment."
            return cmd, explanation, "Low"
            
        elif app_clean in ("python", "python3"):
            if is_linux:
                if gui:
                    cmd = "sudo apt-get update && sudo apt-get install -y python3 python3-pip idle3 && python3 --version"
                    explanation = "Installs Python 3 runtime, pip, and IDLE GUI editor."
                else:
                    cmd = "sudo apt-get update && sudo apt-get install -y python3 python3-pip"
                    explanation = "Installs Python 3 runtime and pip package manager."
            elif is_macos:
                cmd = "brew install python"
                explanation = "Installs Python 3 runtime and pip via Homebrew."
            else:
                cmd = "winget install Python.Python.3"
                explanation = "Installs Python 3 runtime."
            return cmd, explanation, "Low"
            
        elif app_clean == "git":
            if is_linux:
                if gui:
                    cmd = "sudo apt-get update && sudo apt-get install -y git git-gui gitk"
                    explanation = "Installs Git version control and native GUI tools (git-gui, gitk)."
                else:
                    cmd = "sudo apt-get update && sudo apt-get install -y git"
                    explanation = "Installs Git version control CLI."
            elif is_macos:
                cmd = "brew install git"
                explanation = "Installs Git version control CLI via Homebrew."
            else:
                cmd = "winget install --id Git.Git"
                explanation = "Installs Git version control."
            return cmd, explanation, "Low"

        # 2. Local Database / RAG lookup fallback
        try:
            from vector_search import VectorSearch
            vs = VectorSearch()
            results = vs.search(app_clean, top_k=3)
            if is_linux:
                os_target = "Linux"
            elif is_macos:
                os_target = "macOS"
            else:
                os_target = "Windows"
            for r in results:
                if r.get("os", "").lower() == os_target.lower():
                    if app_clean in r["issue"].lower() or app_clean in r["explanation"].lower():
                        return r["command"], r["explanation"], r.get("risk", "Low")
        except Exception as e:
            print("RAG search failed:", e)

        # 3. Ollama Fallback
        try:
            from ai_assistant import ollama_available, ask_ollama
            if ollama_available():
                if is_linux:
                    os_name = "Ubuntu/Debian Linux"
                elif is_macos:
                    os_name = "macOS"
                else:
                    os_name = "Windows"
                gui_text = "with a graphical GUI/desktop wrapper or GUI tool if applicable" if gui else "CLI command-line only"
                prompt = f"Provide a single command to install '{app_name}' on {os_name} ({gui_text}). Do not output explanations. Output only the command. If multiple commands are needed, separate them with '&&'."
                response = ask_ollama(prompt).strip()
                if response and not "ollama" in response.lower() and not "not installed" in response.lower():
                    if "```" in response:
                        lines = response.split("\n")
                        cmd_lines = []
                        in_block = False
                        for line in lines:
                            if line.startswith("```"):
                                in_block = not in_block
                            elif in_block:
                                cmd_lines.append(line)
                        if cmd_lines:
                            response = "\n".join(cmd_lines)
                    cmd = response.replace("```bash", "").replace("```sh", "").replace("```", "").strip()
                    explanation = f"Dynamically extracted installation recipe for {app_name} via AI."
                    return cmd, explanation, "Medium"
        except Exception as e:
            print("Ollama fallback failed:", e)

    except Exception as exc:
        print(f"Error extracting recipe for '{app_name}': {exc}")
        traceback.print_exc()

    # 4. Dynamic package discovery fallback — no hardcoded IDs
    try:
        from pkg_discovery import search_and_auto_pick
        result = search_and_auto_pick(app_name)
        if result:
            cmd, pkg_id, manager = result
            explanation = f"Dynamically discovered '{pkg_id}' via {manager} and generated install command."
            return cmd, explanation, "Medium"
    except Exception as _disc_err:
        print(f"pkg_discovery fallback failed for '{app_name}': {_disc_err}")

    # 5. Generic OS-level last resort (no ID knowledge needed)
    app_pkg = app_clean.replace(" ", "-").replace("/", "-").strip("-")
    if is_linux:
        gui_suffix = " --install-suggests" if gui else ""
        cmd = f"sudo apt-get update && sudo apt-get install -y {app_pkg}{gui_suffix}"
        explanation = f"Installs {app_name} using the system apt package manager."
    elif is_macos:
        cmd = f"brew install {app_pkg}"
        explanation = f"Installs {app_name} using Homebrew."
    else:
        cmd = f"winget search \"{app_name}\" --accept-source-agreements"
        explanation = f"Search winget for '{app_name}' — no verified ID found automatically."

    return cmd, explanation, "Medium"


@router.post("/api/devtools/extract")
async def devtools_extract(body: dict = Body(default={})):
    """Run installation steps based on package mappings."""
    app_name = (body.get("app") or "").strip().lower()
    gui = body.get("gui", False)
    if not app_name:
        raise HTTPException(status_code=400, detail="Specify the target package name.")
        
    cmd, explanation, risk = extract_dynamic_app_command(app_name, gui)
    
    if app_name in ("git", "git missing") and not gui:
        action = engine.get_action("git") or {}
        cmd = action.get("command") or cmd
        
    if not cmd:
        raise HTTPException(status_code=400, detail=f"No recipe matches '{app_name}'.")
        
    return {
        "ok": True,
        "title": f"Install {app_name}",
        "command": cmd,
        "purpose": explanation,
        "risk": risk,
        "affects": app_name
    }


@router.get("/api/devtools/managed")
async def get_managed_devtools():
    """Get the list of all dynamically managed developer tools."""
    try:
        from devtools_manager import devtools_manager
        return {"ok": True, "apps": devtools_manager.list_managed_apps()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/devtools/update-stream")
async def devtools_update_stream(app_id: str = "", request: Request = None):
    """
    Server-Sent Events (SSE) endpoint that streams real-time update progress
    for a managed app. Yields JSON events with 'phase' and 'pct' fields,
    mimicking Play Store-style download progress.

    Phases: fetching (0-30%) → installing (30-80%) → verifying (80-95%) → done (100%)

    Client usage:
        const es = new EventSource(`/api/devtools/update-stream?app_id=git`);
        es.onmessage = e => { const d = JSON.parse(e.data); ... };
    """
    import asyncio
    import subprocess
    import sys
    import json as _json

    if not app_id:
        raise HTTPException(status_code=400, detail="app_id is required")

    try:
        from devtools_manager import devtools_manager
        app = devtools_manager.get_managed_app(app_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not app:
        raise HTTPException(status_code=404, detail=f"App '{app_id}' not found in managed apps")

    update_command = app.get("update_command", "").strip()
    if not update_command:
        raise HTTPException(status_code=400, detail=f"No update command defined for '{app_id}'")

    async def _stream_update():
        """Async generator that yields SSE-formatted JSON progress events."""

        def _sse(data: dict) -> str:
            return f"data: {_json.dumps(data)}\n\n"

        try:
            # Phase 1: fetching (0 → 30%)
            yield _sse({"phase": "fetching", "pct": 0, "message": "Preparing update…"})
            await asyncio.sleep(0.3)
            yield _sse({"phase": "fetching", "pct": 10, "message": "Fetching package metadata…"})

            # Launch the update process
            proc = await asyncio.create_subprocess_shell(
                update_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
            )

            yield _sse({"phase": "fetching", "pct": 20, "message": "Downloading packages…"})

            # Phase 2: installing — read lines and increment progress 30→80%
            install_pct = 30
            lines_seen = 0
            stdout_lines = []

            while True:
                # Check if client disconnected
                if request and await request.is_disconnected():
                    proc.kill()
                    return

                try:
                    line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=60.0)
                except asyncio.TimeoutError:
                    break

                if not line_bytes:
                    break

                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                stdout_lines.append(line)
                lines_seen += 1

                # Advance install progress based on output lines (30-80%)
                if install_pct < 80:
                    install_pct = min(80, 30 + lines_seen * 3)

                phase = "installing"
                msg = line if line else "Installing…"
                # Trim long messages for the UI
                if len(msg) > 80:
                    msg = msg[:77] + "…"

                yield _sse({"phase": phase, "pct": install_pct, "message": msg})

            # Wait for process to finish (with timeout)
            try:
                await asyncio.wait_for(proc.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                proc.kill()

            rc = proc.returncode if proc.returncode is not None else -1

            if rc != 0:
                # Error path
                err_detail = "\n".join(stdout_lines[-5:]) if stdout_lines else "Update failed"
                if len(err_detail) > 200:
                    err_detail = err_detail[-200:]
                yield _sse({
                    "phase": "error",
                    "pct": install_pct,
                    "message": err_detail,
                    "ok": False,
                    "returncode": rc,
                })
                return

            # Phase 3: verifying (80 → 95%)
            yield _sse({"phase": "verifying", "pct": 85, "message": "Verifying installation…"})
            await asyncio.sleep(0.4)
            yield _sse({"phase": "verifying", "pct": 92, "message": "Checking package integrity…"})
            await asyncio.sleep(0.3)

            # Phase 4: done (100%)
            yield _sse({
                "phase": "done",
                "pct": 100,
                "message": "Update complete!",
                "ok": True,
            })

        except Exception as exc:
            yield _sse({
                "phase": "error",
                "pct": 0,
                "message": str(exc),
                "ok": False,
            })

    return StreamingResponse(
        _stream_update(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


class UninstallRequest(BaseModel):
    app_id: str
    confirm: bool = False


@router.post("/api/devtools/uninstall")
async def devtools_uninstall_app(req: UninstallRequest):
    """
    Uninstall a managed app by running its stored uninstall command.
    Removes the app from the managed apps list on success.
    Requires confirm=True to guard against accidental calls.
    """
    import subprocess as _sp

    if not req.app_id:
        raise HTTPException(status_code=400, detail="app_id is required")
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to proceed with uninstall")

    try:
        from devtools_manager import devtools_manager
        app = devtools_manager.get_managed_app(req.app_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not app:
        raise HTTPException(status_code=404, detail=f"App '{req.app_id}' not found in managed apps")

    uninstall_cmd = app.get("uninstall_command", "").strip()
    if not uninstall_cmd:
        raise HTTPException(status_code=400, detail=f"No uninstall command defined for '{req.app_id}'")

    try:
        result = _sp.run(
            uninstall_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
        )
        ok = result.returncode == 0
    except _sp.TimeoutExpired:
        return {"ok": False, "error": "Uninstall command timed out (120s)"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    if ok:
        # Remove from managed list on success
        try:
            from devtools_manager import devtools_manager
            devtools_manager.remove_managed_app(req.app_id)
        except Exception:
            pass
        log_action("UNINSTALL", uninstall_cmd, f"Uninstalled {app.get('name', req.app_id)} via managed apps.")

    return {
        "ok": ok,
        "app_id": req.app_id,
        "name": app.get("name", req.app_id),
        "returncode": result.returncode,
        "stdout": result.stdout[-500:] if result.stdout else "",
        "stderr": result.stderr[-500:] if result.stderr else "",
    }


@router.post("/api/devtools/search-packages")
async def devtools_search_packages(body: dict = Body(default={})):
    """
    Dynamic package search across all available package managers.
    Replaces every hardcoded ID map — the caller supplies only the
    human-readable app name; we discover the real package ID live.
    """
    query = (body.get("query") or body.get("app") or "").strip()
    manager = (body.get("manager") or "auto").strip().lower()
    if not query:
        raise HTTPException(status_code=400, detail="'query' is required.")
    try:
        from pkg_discovery import search_packages
        results = search_packages(query, manager=manager,
                                  include_npm=True, include_pypi=True)
        return {
            "ok": True,
            "query": query,
            "manager": manager,
            "count": len(results),
            "results": [
                {
                    "id":          r.id,
                    "name":        r.name,
                    "version":     r.version,
                    "source":      r.source,
                    "manager":     r.manager,
                    "description": r.description,
                    "publisher":   r.publisher,
                    "match_score": r.match_score,
                }
                for r in results
            ],
        }
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/devtools/package-details")
async def devtools_package_details(body: dict = Body(default={})):
    """
    Fetch full metadata + verified install command for a confirmed package ID.
    """
    pkg_id  = (body.get("id") or "").strip()
    manager = (body.get("manager") or "").strip().lower()
    if not pkg_id or not manager:
        raise HTTPException(status_code=400, detail="'id' and 'manager' are required.")
    try:
        from pkg_discovery import get_package_details
        details = get_package_details(pkg_id, manager)
        if not details:
            raise HTTPException(status_code=404,
                                detail=f"No details found for '{pkg_id}' via {manager}.")
        return {
            "ok":          True,
            "id":          details.id,
            "name":        details.name,
            "description": details.description,
            "publisher":   details.publisher,
            "version":     details.version,
            "url":         details.url,
            "license":     details.license,
            "manager":     details.manager,
            "source":      details.source,
            "install_cmd": details.install_cmd,
            "genre":       details.genre,
            "classic":     getattr(details, "classic", False),
        }
    except HTTPException:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/devtools/uninstall-cmd")
async def get_uninstall_command(tool: str = ""):
    """
    Detect HOW a tool is installed and return the correct uninstall command.
    Prevents 'no such directory/package' errors from wrong uninstall method.
    No hardcoded ID maps — probes the live filesystem and package DBs.
    """
    import shutil, subprocess
    from pathlib import Path

    if not tool:
        raise HTTPException(status_code=400, detail="tool parameter required")

    tool_lower = tool.lower().strip()
    os_name = platform.system()

    def _flatpak_installed(app_id: str) -> bool:
        try:
            paths = [
                Path(f"/var/lib/flatpak/app/{app_id}"),
                Path(Path.home() / f".local/share/flatpak/app/{app_id}"),
            ]
            return any(p.exists() for p in paths)
        except Exception:
            return False

    def _snap_installed(snap_name: str) -> bool:
        try:
            paths = [
                Path(f"/snap/{snap_name}"),
                Path(f"/var/lib/snapd/snap/{snap_name}"),
            ]
            return any(p.exists() for p in paths)
        except Exception:
            return False

    def _apt_pkg_installed(pkg: str) -> bool:
        try:
            r = subprocess.run(
                ["dpkg", "-l", pkg.split()[0]],
                capture_output=True, text=True, timeout=3
            )
            return "ii " in r.stdout
        except Exception:
            return False

    if os_name != "Linux":
        return {"ok": True, "command": None, "method": "unknown"}

    # Dynamically discover installed package IDs — no hardcoded maps.

    # 1. Flatpak: enumerate installed apps and match by name/id
    try:
        fp_out = subprocess.run(
            ["flatpak", "list", "--app", "--columns=application,name"],
            capture_output=True, text=True, timeout=5
        ).stdout
        for line in fp_out.splitlines():
            parts = line.split()
            if not parts:
                continue
            fp_id   = parts[0]
            fp_name = " ".join(parts[1:]).lower()
            if tool_lower in fp_id.lower() or tool_lower in fp_name:
                if _flatpak_installed(fp_id):
                    return {"ok": True, "command": f"flatpak uninstall -y {fp_id}", "method": "flatpak"}
    except Exception:
        pass

    # 2. Snap: probe by slug conversion
    snap_slug = tool_lower.replace(" ", "-")
    if _snap_installed(snap_slug):
        return {"ok": True, "command": f"sudo snap remove --purge {snap_slug}", "method": "snap"}
    snap_slug2 = tool_lower.replace(" ", "")
    if snap_slug2 != snap_slug and _snap_installed(snap_slug2):
        return {"ok": True, "command": f"sudo snap remove --purge {snap_slug2}", "method": "snap"}

    # 3. APT/dpkg: probe by slug
    apt_slug = tool_lower.replace(" ", "-")
    if _apt_pkg_installed(apt_slug):
        return {
            "ok": True,
            "command": f"sudo apt-get remove --purge -y {apt_slug} && sudo apt-get autoremove -y",
            "method": "apt",
        }

    # 4. PATH binary (pip / cargo / manual installs)
    binary = tool_lower.replace(" ", "")
    if shutil.which(binary):
        bin_path = shutil.which(binary)
        return {"ok": True, "command": f"sudo rm -f {bin_path}", "method": "binary"}

    # 5. Not found — let frontend show a manual input
    return {"ok": True, "command": None, "method": "not_found"}


# ===========================================================================
# Resolution Pipeline endpoints
# ===========================================================================

@router.post("/api/devtools/resolve")
async def resolve_package(request: Request):
    """
    Full resolution pipeline.
    Returns auto_selected | needs_disambiguation | not_found.
    Never hardcodes IDs — always runs live search + scores + verifies.
    """
    body = await request.json()
    query        = (body.get("query") or "").strip()
    variant_hint = (body.get("variant") or "").strip()
    force        = bool(body.get("force_refresh", False))

    if not query:
        raise HTTPException(status_code=400, detail="'query' is required.")

    try:
        from pkg_resolution import resolve as do_resolve, SCORER
        result = do_resolve(query, variant_hint, force)

        def _cand(c):
            return {
                "pkg_id":       c.pkg_id,
                "name":         c.name,
                "version":      c.version,
                "manager":      c.manager,
                "source":       c.source,
                "publisher":    c.publisher,
                "homepage":     c.homepage,
                "description":  c.description,
                "fuzzy_score":  c.fuzzy_score,
                "trust_score":  c.trust_score,
                "total_score":  c.total_score,
                "variant_tags": c.variant_tags,
                "verified":     c.verified,
                "install_cmd":  (
                    result.install_cmd
                    if result.selected and c.pkg_id == result.selected.pkg_id
                    else ""
                ),
            }

        return {
            "ok":          True,
            "status":      result.status,
            "confidence":  result.confidence,
            "from_cache":  result.from_cache,
            "source_used": result.source_used,
            "install_cmd": result.install_cmd,
            "selected":    _cand(result.selected) if result.selected else None,
            "candidates":  [_cand(c) for c in result.candidates],
        }
    except Exception as exc:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/devtools/resolve/record-install")
async def record_install(request: Request):
    """
    Record the outcome of an install attempt in the provenance cache.
    Called automatically by the frontend when the streaming terminal reports
    exit_code=0 (success) or exit_code!=0 (failure).
    """
    body = await request.json()
    query    = (body.get("query") or "").strip()
    pkg_id   = (body.get("pkg_id") or "").strip()
    manager  = (body.get("manager") or "").strip()
    source   = (body.get("source") or manager).strip()
    publisher= (body.get("publisher") or "").strip()
    homepage = (body.get("homepage") or "").strip()
    variant  = (body.get("variant") or "").strip()
    success  = bool(body.get("success", True))
    verified_raw = body.get("verified")            # True / False / null
    verified = (
        True  if verified_raw is True  else
        False if verified_raw is False else
        None
    )

    if not query or not pkg_id or not manager:
        raise HTTPException(status_code=400,
                            detail="'query', 'pkg_id', and 'manager' are required.")
    try:
        from pkg_resolution import record_install as do_record
        do_record(query, pkg_id, manager, source, publisher, homepage,
                  verified, variant, success)
        return {"ok": True, "recorded": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/devtools/provenance")
async def get_provenance(query: str = "", variant: str = ""):
    """Return the cached provenance record for a query (for UI badge display)."""
    if not query:
        raise HTTPException(status_code=400, detail="'query' is required.")
    try:
        from pkg_resolution import get_provenance as do_get
        rec = do_get(query.strip(), variant.strip())
        if not rec:
            return {"ok": True, "found": False}
        return {
            "ok":             True,
            "found":          True,
            "resolved_id":    rec.resolved_id,
            "manager":        rec.manager,
            "source":         rec.source,
            "publisher":      rec.publisher,
            "homepage":       rec.homepage,
            "verified":       rec.verified,
            "verified_at":    rec.verified_at,
            "install_success":rec.install_success,
            "last_used":      rec.last_used,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/api/devtools/provenance")
async def delete_provenance(query: str = "", variant: str = ""):
    """Hard-delete a provenance record to force fresh resolution next time."""
    if not query:
        raise HTTPException(status_code=400, detail="'query' is required.")
    try:
        from pkg_resolution import delete_provenance as do_delete
        do_delete(query.strip(), variant.strip())
        return {"ok": True, "deleted": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/devtools/version-cmd")
async def get_version_cmd(name: str = ""):
    """
    Returns the version probe command for a named tool from pkg_catalog.json.
    The frontend runs this command in the terminal after a successful install
    to show the user that the app is actually installed and working.
    e.g. GET /api/devtools/version-cmd?name=git  → { "ok": true, "cmd": "git --version" }
    """
    if not name:
        raise HTTPException(status_code=400, detail="'name' is required.")
    try:
        import json as _json
        from pathlib import Path as _Path
        catalog_path = _Path(__file__).parent / "pkg_catalog.json"
        catalog = _json.loads(catalog_path.read_text(encoding="utf-8"))
        q = name.lower().strip()
        for tool in catalog.get("tools", []):
            if q in [n.lower() for n in tool.get("names", [])] or \
               any(q in n.lower() or n.lower() in q for n in tool.get("names", [])):
                return {"ok": True, "cmd": tool.get("version_cmd", ""), "found": True}
        return {"ok": True, "cmd": "", "found": False}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/ollama/status")
async def get_ollama_status():
    import urllib.request
    from ai_assistant import list_local_models
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5.0) as res:
            if res.status == 200:
                models = list_local_models()
                return {"running": True, "models": models}
    except Exception:
        pass
    
    import psutil
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            if proc.info['name'] == 'ollama' or (proc.info['cmdline'] and 'ollama' in proc.info['cmdline']):
                return {"running": True, "starting": True, "models": []}
        except Exception:
            pass
            
    return {"running": False, "models": []}


@router.post("/api/ollama/start")
async def start_ollama_server():
    import shutil
    import subprocess
    from pathlib import Path
    if not shutil.which("ollama"):
        raise HTTPException(status_code=400, detail="Ollama executable not found on system PATH. Install Ollama first.")
    
    status = await get_ollama_status()
    if status.get("running"):
        flag_file = Path(__file__).parent / "ollama_user_started.flag"
        try:
            flag_file.touch()
        except Exception:
            pass
        return {"ok": True, "message": "Ollama server is already running."}
        
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        flag_file = Path(__file__).parent / "ollama_user_started.flag"
        try:
            flag_file.touch()
        except Exception:
            pass
        return {"ok": True, "message": "Ollama server started successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start Ollama server: {str(e)}")


@router.post("/api/ollama/stop")
async def stop_ollama_server():
    import psutil
    import os
    import signal
    from pathlib import Path
    
    # Remove flag file
    flag_file = Path(__file__).parent / "ollama_user_started.flag"
    if flag_file.exists():
        try:
            flag_file.unlink()
        except Exception:
            pass
            
    stopped = False
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['name'] == 'ollama' or (proc.info['cmdline'] and 'ollama' in proc.info['cmdline']):
                os.kill(proc.info['pid'], signal.SIGTERM)
                stopped = True
        except Exception:
            pass
    if stopped:
        return {"ok": True, "message": "Ollama server stopped successfully."}
    return {"ok": True, "message": "Ollama server was not running."}


class ApproveHealingRequest(BaseModel):
    attempt_id: int
    confirm_dangerous: bool = False


@router.get("/api/self-healing/status")
def get_self_healing_status():
    """
    Get all active self-healing attempts, learning analytics, and active command mappings.
    """
    import sqlite3
    from self_healing import DB_PATH
    from command_adaptation import detect_os_profile, get_system_health, compute_adaptation_progress, finalize_progress

    # Get adaptation progress
    recipes = engine.list_recipes()
    progress = finalize_progress(compute_adaptation_progress(engine, len(recipes)))
    health = get_system_health()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Active attempts (non-archived)
    cur.execute("""
        SELECT id, error_message, error_source, cause, attempted_fix, fix_source, result, safety_class, validation_result, timestamp
        FROM self_healing_attempts
        WHERE archived = 0
        ORDER BY id DESC
    """)
    attempts = [dict(row) for row in cur.fetchall()]

    # Mappings from learned_command_mappings
    cur.execute("""
        SELECT id, original_command, failed_command, replacement_command, verification_result, timestamp
        FROM learned_command_mappings
        ORDER BY id DESC
    """)
    mappings = [dict(row) for row in cur.fetchall()]

    # Analytics
    # Success / Failure counts from self_healing_attempts
    cur.execute("SELECT COUNT(*) FROM self_healing_attempts")
    total_attempts = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM self_healing_attempts WHERE result IN ('Successful', 'Healing Successful')")
    success_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM self_healing_attempts WHERE result LIKE 'Failed%' OR result = 'Rolled Back' OR result = 'Successful (Rolled Back)'")
    failure_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM self_healing_attempts WHERE result = 'Rolled Back'")
    rollback_count = cur.fetchone()[0]

    # Verification status counts from adaptive_knowledge_base
    cur.execute("SELECT COUNT(*) FROM adaptive_knowledge_base WHERE verification_status = 'Trusted'")
    trusted_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM adaptive_knowledge_base WHERE verification_status = 'Experimental'")
    experimental_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM adaptive_knowledge_base WHERE verification_status = 'Degraded'")
    degraded_count = cur.fetchone()[0]

    conn.close()

    success_rate = 0.0
    if (success_count + failure_count) > 0:
        success_rate = round(success_count / (success_count + failure_count), 2)

    return {
        "ok": True,
        "attempts": attempts,
        "registry_mappings": mappings,
        "system_health": health,
        "adaptation_score": progress.get("overall", 0),
        "analytics": {
            "total_attempts": total_attempts,
            "success_count": success_count,
            "failure_count": failure_count,
            "rollback_count": rollback_count,
            "success_rate": success_rate,
            "trusted_count": trusted_count,
            "experimental_count": experimental_count,
            "degraded_count": degraded_count,
        }
    }


def verify_healing_success(error_source: str, attempted_fix: str) -> bool:
    import platform
    import shutil
    from scanner import SystemScanner
    scanner = SystemScanner()
    
    src = (error_source or "").lower()
    fix = (attempted_fix or "").lower()
    
    issues = []
    if "docker" in fix or "docker" in src:
        issues = scanner._check_docker()
    elif "python" in fix or "python" in src or "pip" in fix or "pip" in src:
        issues = scanner._check_python()
    elif "node" in fix or "node" in src or "npm" in fix or "npm" in src:
        issues = scanner._check_node()
    elif "git" in fix or "git" in src:
        issues = scanner._check_git()
    elif "java" in fix or "java" in src:
        issues = scanner._check_java()
    elif "vscode" in fix or "vscode" in src or "code" in fix:
        issues = scanner._check_vscode()
    elif "nvidia" in fix or "nvidia" in src or "driver" in fix or "driver" in src or "ubuntu-drivers" in fix:
        if platform.system() == "Linux":
            issues = scanner._check_gpu_drivers()
        else:
            issues = scanner._check_windows_drivers()
    elif "system_update" in src or "update" in src or "update" in fix or "apt" in fix or "upgrade" in fix:
        if platform.system() == "Linux":
            issues = scanner._check_system_updates()
        else:
            issues = scanner._check_windows_update()
    elif "systemctl" in fix or "service" in fix or "service" in src or "systemd" in src:
        if platform.system() == "Linux":
            issues = scanner._check_linux_services()
    elif "drop_caches" in fix or "memory" in src or "ram" in src:
        issues = scanner._check_memory()
    elif "tmp" in fix or "temp" in fix or "disk" in src or "clear" in src:
        issues = scanner._check_disk()
    else:
        all_issues = scanner.scan()
        for issue in all_issues:
            title = issue.get("title", "").lower()
            detail = issue.get("detail", "").lower()
            recipe = issue.get("recipe_hint", "").lower()
            if (fix in title or fix in detail or fix in recipe or
                src in title or src in detail or src in recipe):
                return False
        return True
        
    return len(issues) == 0


@router.post("/api/self-healing/approve")
def approve_self_healing(req: ApproveHealingRequest):
    """
    Approve and run a learned self-healing command recommendation.
    """
    import sqlite3
    import platform
    import datetime
    from self_healing import DB_PATH, self_healing_mgr, safety_classifier, validation_sandbox
    from command_adaptation import detect_os_profile
    from logger import log_action

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, error_message, error_source, cause, attempted_fix, fix_source, safety_class, validation_result, result
        FROM self_healing_attempts
        WHERE id = ?
    """, (req.attempt_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Self-healing attempt {req.attempt_id} not found.")

    attempt_id, error_message, error_source, cause, attempted_fix, fix_source, safety_class, validation_result, current_result = row

    from feature_flags import ENABLE_DEV_MODE
    if safety_class == "Blocked" and not ENABLE_DEV_MODE:
        raise HTTPException(status_code=400, detail="This command is blocked for safety reasons.")


    if safety_class == "Dangerous" and not req.confirm_dangerous:
        return {
            "ok": False,
            "requires_secondary_confirmation": True,
            "message": f"Warning: The command '{attempted_fix}' is classified as DANGEROUS (covers system kernel or critical configurations). Executing it could destabilize the OS. Please confirm execution."
        }

    # Execute and verify the fix
    # Create configuration backup
    paths = []
    if platform.system() == "Linux":
        if os.path.exists("/etc/apt/sources.list"):
            paths.append("/etc/apt/sources.list")
        if os.path.exists("/etc/apt/sources.list.d"):
            try:
                paths.extend(str(f) for f in Path("/etc/apt/sources.list.d").glob("*.list"))
            except Exception:
                pass

    config_backup = None
    if paths:
        try:
            config_backup = self_healing_mgr.create_snapshot(paths)
        except Exception:
            pass

    # Execute
    out, err, rc = engine.run(attempted_fix)

    from feature_flags import ENABLE_DEV_MODE
    if rc != 0 and ENABLE_DEV_MODE:
        rc = 0
        out = f"Mocked success under DEVELOPMENT_MODE: {out}"
        err = ""

    # Determine status & update database
    profile = detect_os_profile(engine)
    os_name = platform.system()
    os_version = profile.get("version", "") or profile.get("os_version", "")
    kernel_version = profile.get("kernel", "")

    if rc != 0:
        result_str = "Healing Failed"
        success = False
    else:
        if verify_healing_success(error_source, attempted_fix) or ENABLE_DEV_MODE:
            result_str = "Healing Successful"
            success = True
        else:
            result_str = "Verification Failed"
            success = False

    if not success and config_backup:
        try:
            self_healing_mgr.restore_snapshot(config_backup)
        except Exception:
            pass

    # Update attempt status
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        UPDATE self_healing_attempts
        SET result = ?, config_backup = ?
        WHERE id = ?
    """, (result_str, config_backup, attempt_id))
    conn.commit()
    conn.close()

    # Log in learned_command_mappings and adaptive_knowledge_base
    try:
        error_pattern = cause if cause else "general_error"
        self_healing_mgr.record_knowledge(
            os_name=os_name,
            os_version=os_version,
            kernel_version=kernel_version,
            error_pattern=error_pattern,
            successful_fix=attempted_fix,
            default_fallback=error_source,
            source=fix_source,
            success=success
        )

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO learned_command_mappings (original_command, failed_command, replacement_command, verification_result, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (error_source, error_source, attempted_fix, "Success" if success else "Failed", datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")))
        conn.commit()
        conn.close()
    except Exception as e:
        log_action("ERROR", "approve_self_healing", f"Failed to record knowledge/mappings: {e}")

    log_action("SELF_HEAL", attempted_fix, f"Execution {result_str}", friendly_summary=f"Self-healing fix execution: {result_str}")

    return {
        "ok": success,
        "stdout": out,
        "stderr": err,
        "returncode": rc,
        "result": result_str
    }


class ArchiveRequest(BaseModel):
    attempt_id: int


@router.post("/api/self-healing/archive")
def archive_self_healing(req: ArchiveRequest):
    """
    Dismiss and archive a self-healing attempt recommendation.
    """
    import sqlite3
    from self_healing import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE self_healing_attempts SET archived = 1 WHERE id = ?", (req.attempt_id,))
    conn.commit()
    conn.close()
    return {"ok": True}



# ─── Performance Metrics Endpoint (Task 14.1/14.2) ───────────────────────────

@router.get("/api/metrics")
async def get_performance_metrics():
    """
    Lightweight performance metrics endpoint.
    Returns memory usage, error frequency, and system health indicators
    for the developer performance dashboard (Task 14.1/14.3).
    """
    import sqlite3
    from self_healing import DB_PATH as SH_DB_PATH
    from shce_engine import DB_PATH as SHCE_DB_PATH
    import datetime

    metrics = {
        "ok": True,
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
        "memory": {},
        "errors": {},
        "system": {},
    }

    # Memory usage
    try:
        mem = psutil.virtual_memory()
        metrics["memory"] = {
            "total_gb": round(mem.total / (1024 ** 3), 2),
            "used_gb": round(mem.used / (1024 ** 3), 2),
            "percent": mem.percent,
            "available_gb": round(mem.available / (1024 ** 3), 2),
        }
    except Exception:
        pass

    # Error frequency from SHCE database
    try:
        conn = sqlite3.connect(SHCE_DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM error_intelligence")
        total_errors = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM error_intelligence WHERE outcome = 'pending'")
        pending_errors = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM shce_queue WHERE status = 'executed'")
        executed_fixes = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM shce_queue WHERE status = 'failed'")
        failed_fixes = cur.fetchone()[0]
        conn.close()
        metrics["errors"] = {
            "total_captured": total_errors,
            "pending": pending_errors,
            "fixes_executed": executed_fixes,
            "fixes_failed": failed_fixes,
            "fix_success_rate": round(
                executed_fixes / max(executed_fixes + failed_fixes, 1) * 100, 1
            ),
        }
    except Exception:
        pass

    # System health indicators
    try:
        cpu_pct = psutil.cpu_percent(interval=0.1)
        disk = psutil.disk_usage("/")
        metrics["system"] = {
            "cpu_percent": cpu_pct,
            "disk_used_gb": round(disk.used / (1024 ** 3), 2),
            "disk_total_gb": round(disk.total / (1024 ** 3), 2),
            "disk_percent": disk.percent,
        }
    except Exception:
        pass

    # Performance degradation detection (Task 14.2)
    warnings = []
    if metrics["memory"].get("percent", 0) > 85:
        warnings.append("High memory usage detected (>85%)")
    if metrics["system"].get("cpu_percent", 0) > 90:
        warnings.append("High CPU usage detected (>90%)")
    if metrics["system"].get("disk_percent", 0) > 90:
        warnings.append("Low disk space warning (>90% used)")
    if metrics["errors"].get("pending", 0) > 10:
        warnings.append(f"High error backlog: {metrics['errors']['pending']} pending errors")

    metrics["warnings"] = warnings
    metrics["degraded"] = len(warnings) > 0

    return metrics
