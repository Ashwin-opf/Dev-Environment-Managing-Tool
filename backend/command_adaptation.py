"""
Centralized OS command adaptation layer for Repair, Optimize, and Dev Tools.
"""
from __future__ import annotations

import json
import platform
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

BASE_DIR = Path(__file__).parent
HISTORY_FILE = BASE_DIR / "adaptation_history.json"
ERRORS_FILE = BASE_DIR / "adaptation_errors.json"

GENERIC_ACTION_LABELS = {
    "system_update": "Update Packages",
    "temp_cleanup": "Clean Cache",
    "browser_cache_cleanup": "Clean Browser Cache",
    "boost_ram": "Boost RAM",
    "startup_list": "Repair Startup",
    "remove_orphans": "Repair Packages",
    "driver_package_update": "Update Drivers",
    "driver_package_check": "Check Driver Updates",
}

TAG_RULES: list[tuple[tuple[str, ...], list[str]]] = [
    (("python", "pip"), ["python", "pip", "programming", "developer"]),
    (("node", "npm"), ["nodejs", "npm", "javascript", "developer"]),
    (("git",), ["git", "version-control", "developer"]),
    (("docker",), ["docker", "containers", "devops"]),
    (("java", "java_home"), ["java", "jdk", "developer"]),
    (("vs code", "code"), ["vscode", "editor", "developer"]),
    (("android",), ["android", "mobile", "developer"]),
    (("ollama",), ["ollama", "ai", "llm"]),
    (("nvidia", "driver"), ["gpu", "nvidia", "drivers", "graphics"]),
    (("temp", "cache", "browser"), ["cleanup", "optimize", "storage"]),
    (("ram", "startup", "slow"), ["performance", "optimize", "memory"]),
    (("chocolatey",), ["windows", "package-manager"]),
    (("system package", "update"), ["update", "packages", "system"]),
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_json_list(path: Path, items: list[dict], limit: int = 200) -> None:
    path.write_text(json.dumps(items[-limit:], indent=2), encoding="utf-8")


def detect_os_profile(engine: Any) -> dict[str, Any]:
    os_name = platform.system()
    kernel = platform.release()
    distro_id = getattr(engine, "distro", "unknown")
    os_label = os_name
    package_manager = "unknown"
    version = ""

    if os_name == "Linux":
        try:
            release = platform.freedesktop_os_release()
            pretty = release.get("PRETTY_NAME") or release.get("NAME") or "Linux"
            version = release.get("VERSION_ID") or ""
            dist_id = (release.get("ID") or "").lower()
            os_label = pretty.split("(")[0].strip()
            if version and version not in os_label:
                os_label = f"{os_label} {version}".strip()
            distro_id = getattr(engine, "distro", dist_id or "debian")
        except Exception:
            os_label = "Linux"
    elif os_name == "Windows":
        os_label = "Windows"
        package_manager = "winget"
    elif os_name == "Darwin":
        os_label = "macOS"
        package_manager = "brew"

    pm_map = {
        "debian": "APT",
        "fedora": "DNF",
        "arch": "Pacman",
        "opensuse": "Zypper",
        "darwin": "Homebrew",
        "windows": "Winget",
    }
    if os_name == "Linux":
        package_manager = pm_map.get(distro_id, "APT")
    elif os_name == "Windows":
        package_manager = "Winget"
    elif os_name == "Darwin":
        package_manager = "Homebrew"

    return {
        "os_name": os_name,
        "os_label": os_label,
        "kernel": kernel,
        "distro": distro_id,
        "package_manager": package_manager,
        "version": version,
        "architecture": platform.machine(),
    }


def _recipe_tags(issue: str, explanation: str = "") -> list[str]:
    text = f"{issue} {explanation}".lower()
    tags: list[str] = []
    for needles, values in TAG_RULES:
        if any(needle in text for needle in needles):
            tags.extend(values)
    for token in re.findall(r"[a-z0-9]+", text):
        if len(token) > 2 and token not in tags:
            tags.append(token)
    return list(dict.fromkeys(tags))[:12]


def enrich_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    issue = recipe.get("issue", "")
    explanation = recipe.get("explanation", "")
    tags = _recipe_tags(issue, explanation)
    keywords = " ".join(dict.fromkeys([issue, explanation, " ".join(tags)])).strip()
    enriched = dict(recipe)
    enriched["tags"] = tags
    enriched["keywords"] = keywords
    return enriched


def enrich_recipes(recipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [enrich_recipe(recipe) for recipe in recipes]


def search_recipes(recipes: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    q = query.lower().strip()
    if not q:
        return recipes
    tokens = [token for token in re.findall(r"[a-z0-9]+", q) if token]
    results = []
    for recipe in recipes:
        haystack = " ".join([
            recipe.get("issue", ""),
            recipe.get("explanation", ""),
            recipe.get("command", ""),
            " ".join(recipe.get("tags") or []),
            recipe.get("keywords", ""),
        ]).lower()
        if q in haystack or all(token in haystack for token in tokens):
            results.append(recipe)
    return results


def build_command_mappings(engine: Any) -> list[dict[str, str]]:
    mappings: list[dict[str, str]] = []
    for key, label in GENERIC_ACTION_LABELS.items():
        action = engine.get_action(key)
        if not action:
            continue
        mappings.append({
            "action": label,
            "generic": key,
            "command": action.get("command", ""),
            "risk": action.get("risk", "Low"),
            "validated": "true" if action.get("command") else "false",
        })
    return mappings


def get_system_health() -> int | str:
    unresolved_count = 0
    try:
        from self_healing import DB_PATH
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(DISTINCT error_message) FROM self_healing_attempts 
            WHERE archived = 0 AND result != 'Successful' AND result != 'Healing Successful'
        """)
        unresolved_count = cur.fetchone()[0]
        conn.close()
    except Exception:
        pass

    try:
        from app_context import scanner
        active_issues_count = len(getattr(scanner, "latest_issues", []))
    except Exception:
        active_issues_count = 0

    total_problems = unresolved_count + active_issues_count
    return max(10, 100 - (total_problems * 5))


def compute_adaptation_progress(engine: Any, recipe_count: int) -> dict[str, int]:
    import platform
    import shutil
    
    actions = engine.list_actions()
    action_keys = {item.get("key") for item in actions if item.get("key")}
    
    # 1. Package commands coherence
    package_actions = sum(1 for item in actions if "update" in item.get("key", "") or "orphan" in item.get("key", ""))
    package_score = min(100, int(package_actions / 2 * 100)) if package_actions else 0
    
    # 2. Optimize score
    total_generic = len(GENERIC_ACTION_LABELS)
    mapped = len(actions)
    optimize_base = int(mapped / max(total_generic, 1) * 100)
    
    # 3. Devtools score based on executable availability
    from tool_detector import (
        python_installed, node_installed, npm_installed, git_installed,
        docker_installed, vscode_installed, java_installed, pip_installed,
        snap_installed, android_studio_installed, poetry_installed, pnpm_installed,
        ollama_installed
    )
    
    tool_checks = {
        "python": python_installed(),
        "python3": python_installed(),
        "node": node_installed(),
        "npm": npm_installed(),
        "git": git_installed(),
        "docker": docker_installed(),
        "java": java_installed(),
        "code": vscode_installed(),
        "poetry": poetry_installed(),
        "pnpm": pnpm_installed(),
        "pip": pip_installed(),
        "snap": snap_installed(),
        "android": android_studio_installed(),
        "ollama": ollama_installed(),
    }
    
    devtools_supported = 0
    devtools_total = 0
    for tool in ["python", "python3", "node", "npm", "git", "docker", "java", "code", "poetry", "pnpm"]:
        devtools_total += 1
        if tool_checks.get(tool):
            devtools_supported += 1
    devtools_score = int(devtools_supported / devtools_total * 100)
    
    # 4. Repair score
    repair_score = int(min(recipe_count, 24) / 24 * 100)
    
    # Check key features support
    driver_supported = "driver_package_update" in action_keys or "driver_package_check" in action_keys
    package_upgrade_supported = "system_update" in action_keys
    self_healing_supported = True
    
    penalty = 0
    if not driver_supported:
        penalty += 15
    if not package_upgrade_supported:
        penalty += 15
    if not self_healing_supported:
        penalty += 10
        
    # Query database self-healing core success mappings
    successful_healings = 0
    learned_mappings = 0
    try:
        from self_healing import DB_PATH
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM self_healing_attempts 
            WHERE archived = 0 AND result IN ('Successful', 'Healing Successful')
        """)
        successful_healings = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM learned_command_mappings")
        learned_mappings = cur.fetchone()[0]
        conn.close()
    except Exception:
        pass
        
    healing_bonus = (successful_healings * 5) + (learned_mappings * 5)
    
    # Internet connectivity RAG bonus
    has_internet = False
    try:
        has_internet = engine._check_internet()
    except Exception:
        pass
    internet_bonus = 15 if has_internet else 0
    
    repair_score = min(100, max(10, repair_score - penalty + healing_bonus + internet_bonus))
    optimize_score = min(100, max(10, optimize_base - penalty + healing_bonus + internet_bonus))
    devtools_score = min(100, max(10, devtools_score - penalty + healing_bonus + internet_bonus))
    package_score = min(100, max(10, package_score + healing_bonus + internet_bonus))
    
    # Enforce rule: prevent 100% coherence score if any declared core feature is unsupported
    core_features = ["system_update", "temp_cleanup", "boost_ram", "startup_list"]
    core_supported = all(f in action_keys for f in core_features)
    
    if not core_supported or not driver_supported:
        repair_score = min(95, repair_score)
        optimize_score = min(95, optimize_score)
        devtools_score = min(95, devtools_score)
        package_score = min(95, package_score)

    return {
        "repair": repair_score,
        "optimize": optimize_score,
        "devtools": devtools_score,
        "package_commands": package_score,
        "overall": 0,
    }



def finalize_progress(progress: dict[str, int]) -> dict[str, int]:
    values = [progress["repair"], progress["optimize"], progress["devtools"], progress["package_commands"]]
    progress["overall"] = int(sum(values) / len(values))
    return progress


def record_history(event: str, generic: str, converted: str, status: str, detail: str = "") -> None:
    items = _load_json_list(HISTORY_FILE)
    items.append({
        "timestamp": _utc_now(),
        "event": event,
        "generic": generic,
        "converted": converted,
        "status": status,
        "detail": detail,
    })
    _save_json_list(HISTORY_FILE, items)


def record_error(source: str, command: str, error: str, correction: str = "", correction_status: str = "") -> None:
    items = _load_json_list(ERRORS_FILE)
    items.append({
        "timestamp": _utc_now(),
        "source": source,
        "command": command,
        "error": error,
        "correction": correction,
        "correction_status": correction_status,
    })
    _save_json_list(ERRORS_FILE, items)


def get_history(limit: int = 50) -> list[dict]:
    return list(reversed(_load_json_list(HISTORY_FILE)[-limit:]))


def get_errors(limit: int = 50) -> list[dict]:
    return list(reversed(_load_json_list(ERRORS_FILE)[-limit:]))


def validate_mappings(engine: Any, safety: Any) -> list[dict[str, Any]]:
    results = []
    for mapping in build_command_mappings(engine):
        command = mapping.get("command", "")
        blocked, reason = safety.validate(command, mapping.get("risk", "Low"))
        results.append({
            **mapping,
            "valid": not blocked,
            "reason": reason or "",
        })
    return results


def refresh_adaptation(engine: Any, safety: Any, *, rescan: bool = True, validate: bool = True, refresh_commands: bool = True) -> dict[str, Any]:
    if refresh_commands:
        engine.refresh_command_catalog(force=True)
    profile = detect_os_profile(engine)
    recipes = enrich_recipes(engine.list_recipes())
    progress = finalize_progress(compute_adaptation_progress(engine, len(recipes)))
    health = get_system_health()
    validation = validate_mappings(engine, safety) if validate else []
    if rescan:
        record_history(
            "os_rescan",
            "system",
            profile["os_label"],
            "success",
            f"Package manager: {profile['package_manager']}",
        )
    if refresh_commands:
        record_history(
            "refresh_commands",
            "catalog",
            profile["package_manager"],
            "success",
            f"Loaded {len(engine.list_actions())} OS-specific actions",
        )
        
    # Auto heal if score is below 100
    if progress.get("overall", 0) < 100 or progress.get("devtools", 0) < 100 or progress.get("optimize", 0) < 100 or progress.get("repair", 0) < 100:
        auto_heal_adaptation_scores(engine)
        progress = finalize_progress(compute_adaptation_progress(engine, len(recipes)))

    return {
        "ok": True,
        "profile": profile,
        "progress": progress,
        "system_health": health,
        "mappings": build_command_mappings(engine),
        "validation": validation,
        "history": get_history(20),
        "errors": get_errors(20),
    }



def get_adaptation_status(engine: Any, recipe_count: int) -> dict[str, Any]:
    profile = detect_os_profile(engine)
    progress = finalize_progress(compute_adaptation_progress(engine, recipe_count))
    
    # Auto heal if score is below 100
    if progress.get("overall", 0) < 100 or progress.get("devtools", 0) < 100 or progress.get("optimize", 0) < 100 or progress.get("repair", 0) < 100:
        auto_heal_adaptation_scores(engine)
        progress = finalize_progress(compute_adaptation_progress(engine, recipe_count))
        
    health = get_system_health()
    return {
        "ok": True,
        "profile": profile,
        "progress": progress,
        "system_health": health,
        "mappings": build_command_mappings(engine),
        "history": get_history(20),
        "errors": get_errors(20),
    }


def check_tool_installed(name: str) -> bool:
    from tool_detector import (
        git_installed, docker_installed, poetry_installed, pnpm_installed,
        pip_installed, npm_installed, python_installed, node_installed,
        vscode_installed, java_installed, snap_installed, android_studio_installed,
        ollama_installed
    )
    import shutil
    name = name.lower().strip()
    if name == "git": return git_installed()
    if name == "docker": return docker_installed()
    if name == "poetry": return poetry_installed()
    if name == "pnpm": return pnpm_installed()
    if name == "pip": return pip_installed()
    if name == "npm": return npm_installed()
    if name in ("python", "python3"): return python_installed()
    if name in ("node", "nodejs"): return node_installed()
    if name in ("code", "vscode"): return vscode_installed()
    if name == "java": return java_installed()
    if name == "snap": return snap_installed()
    if name in ("android", "android-studio"): return android_studio_installed()
    if name == "ollama": return ollama_installed()
    if name == "rust": return shutil.which("rustc") is not None
    if name == "go": return shutil.which("go") is not None
    if name == "htop": return shutil.which("htop") is not None
    if name in ("neovim", "nvim"): return shutil.which("nvim") is not None
    if name == "gh": return shutil.which("gh") is not None
    if name == "fzf": return shutil.which("fzf") is not None
    if name == "jq": return shutil.which("jq") is not None
    if name == "tmux": return shutil.which("tmux") is not None
    if name == "pycharm": return shutil.which("pycharm-community") is not None or shutil.which("pycharm") is not None
    if name in ("sublime", "subl"): return shutil.which("subl") is not None
    if name == "postman": return shutil.which("postman") is not None
    if name == "dbeaver": return shutil.which("dbeaver") is not None or shutil.which("dbeaver-ce") is not None
    if name == "slack": return shutil.which("slack") is not None
    if name == "brave": return shutil.which("brave-browser") is not None or shutil.which("brave") is not None
    if name == "chrome": return shutil.which("google-chrome") is not None or shutil.which("chrome") is not None
    if name == "firefox": return shutil.which("firefox") is not None
    return shutil.which(name) is not None


def get_tool_install_command(app_name: str) -> tuple[str, str]:
    import platform
    app_name = app_name.strip().lower()
    is_linux = platform.system() == "Linux"
    
    cmd = ""
    explanation = ""
    
    if app_name in ("git", "git missing"):
        cmd = "sudo apt-get install -y git" if is_linux else "winget install --id Git.Git --exact --silent"
        explanation = "Install Git version control safely."
    elif app_name in ("docker", "docker missing"):
        cmd = "sudo apt-get install -y docker.io && sudo systemctl enable --now docker" if is_linux else "winget install --id Docker.DockerDesktop --exact --silent"
        explanation = "Install Docker Engine container host."
    elif app_name in ("poetry", "poetry missing"):
        cmd = "curl -sSL https://install.python-poetry.org | python3 -"
        explanation = "Install Poetry for Python dependency management."
    elif app_name in ("pnpm", "pnpm missing"):
        cmd = "npm install -g pnpm"
        explanation = "Install pnpm global package manager."
    elif app_name in ("pip", "pip broken"):
        cmd = "sudo apt-get install -y python3-pip" if is_linux else "python -m ensurepip"
        explanation = "Install pip package manager."
    elif app_name in ("npm", "npm broken"):
        cmd = "sudo apt-get install -y npm" if is_linux else "winget install --id OpenJS.NodeJS --exact --silent"
        explanation = "Install npm package manager."
    elif app_name in ("python", "python3", "python missing"):
        cmd = "sudo apt-get install -y python3" if is_linux else "winget install Python.Python.3"
        explanation = "Install Python runtime environment."
    elif app_name in ("node", "node.js", "nodejs", "node.js missing"):
        cmd = "sudo apt-get install -y nodejs" if is_linux else "winget install OpenJS.NodeJS"
        explanation = "Install Node.js JavaScript runtime environment."
    elif app_name in ("code", "vscode", "vs code", "vs code corrupted installation"):
        cmd = "sudo snap install code --classic" if is_linux else "winget install Microsoft.VisualStudioCode"
        explanation = "Install VS Code IDE."
    elif app_name in ("java", "java missing"):
        cmd = "sudo apt-get install -y default-jdk" if is_linux else "winget install Oracle.JDK.21"
        explanation = "Install Java runtime environment."
    elif app_name in ("snap", "snap missing"):
        cmd = "sudo apt-get install -y snapd"
        explanation = "Install Snap package manager."
    elif app_name in ("android", "android-studio", "android studio", "android studio missing"):
        cmd = "sudo snap install android-studio --classic"
        explanation = "Install Android Studio IDE."
    elif app_name in ("ollama", "ollama missing"):
        cmd = "curl -sSL https://ollama.ai/install.sh | sh"
        explanation = "Install Ollama locally."
    elif app_name in ("rust", "rust compiler", "rust missing"):
        cmd = "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y" if is_linux else "winget install Rust.Rustup"
        explanation = "Install Rust compiler and cargo package manager."
    elif app_name in ("go", "golang", "go missing"):
        cmd = "sudo apt-get install -y golang-go" if is_linux else "winget install GoLang.Go"
        explanation = "Install Go programming language runtime."
    elif app_name in ("htop", "htop missing"):
        cmd = "sudo apt-get install -y htop"
        explanation = "Install htop interactive system monitor."
    elif app_name in ("neovim", "nvim", "neovim missing"):
        cmd = "sudo apt-get install -y neovim" if is_linux else "winget install Vim.Neovim"
        explanation = "Install Neovim text editor."
    elif app_name in ("github cli", "gh", "github cli missing"):
        cmd = "sudo apt-get install -y gh" if is_linux else "winget install GitHub.cli"
        explanation = "Install GitHub command line interface."
    elif app_name in ("fzf", "fzf missing"):
        cmd = "sudo apt-get install -y fzf" if is_linux else "winget install junegunn.fzf"
        explanation = "Install fzf command-line fuzzy finder."
    elif app_name in ("jq", "jq missing"):
        cmd = "sudo apt-get install -y jq" if is_linux else "winget install jqlang.jq"
        explanation = "Install jq command-line JSON processor."
    elif app_name in ("tmux", "tmux missing"):
        cmd = "sudo apt-get install -y tmux"
        explanation = "Install tmux terminal multiplexer."
    elif app_name in ("pycharm", "pycharm missing", "pycharm community"):
        cmd = "sudo snap install pycharm-community --classic" if is_linux else "winget install JetBrains.PyCharm.Community"
        explanation = "Install PyCharm Community Edition IDE."
    elif app_name in ("sublime", "sublime text", "sublime missing", "subl"):
        cmd = "sudo snap install sublime-text --classic" if is_linux else "winget install SublimeHQ.SublimeText"
        explanation = "Install Sublime Text editor."
    elif app_name in ("postman", "postman missing"):
        cmd = "sudo snap install postman" if is_linux else "winget install Postman.Postman"
        explanation = "Install Postman API client tool."
    elif app_name in ("dbeaver", "dbeaver ce", "dbeaver ce missing"):
        cmd = "sudo snap install dbeaver-ce" if is_linux else "winget install dbeaver.DBeaver"
        explanation = "Install DBeaver database GUI client."
    elif app_name in ("slack", "slack missing"):
        cmd = "sudo snap install slack" if is_linux else "winget install Slack.Slack"
        explanation = "Install Slack desktop messaging client."
    elif app_name in ("brave", "brave browser", "brave missing"):
        cmd = "sudo snap install brave" if is_linux else "winget install Brave.Brave"
        explanation = "Install Brave privacy-focused browser."
    elif app_name in ("chrome", "google chrome", "google chrome missing"):
        cmd = "wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && sudo apt-get install -y ./google-chrome-stable_current_amd64.deb && rm google-chrome-stable_current_amd64.deb" if is_linux else "winget install Google.Chrome"
        explanation = "Install Google Chrome stable web browser."
    elif app_name in ("firefox", "mozilla firefox", "firefox missing"):
        cmd = "sudo snap install firefox" if is_linux else "winget install Mozilla.Firefox"
        explanation = "Install Mozilla Firefox web browser."
        
    return cmd, explanation


def auto_heal_adaptation_scores(engine: Any) -> None:
    try:
        from shce_engine import shce
        import sqlite3
        from self_healing import DB_PATH
        
        # Check if adaptation is below 100
        recipes = engine.list_recipes()
        progress = finalize_progress(compute_adaptation_progress(engine, len(recipes)))
        
        # Optimize / Driver page healing
        if progress.get("optimize", 0) < 100 or progress.get("repair", 0) < 100:
            actions = engine.list_actions()
            action_keys = {item.get("key") for item in actions if item.get("key")}
            driver_supported = "driver_package_update" in action_keys or "driver_package_check" in action_keys
            if not driver_supported:
                cmd = "map driver_package_update"
                err_msg = "Driver package update is not mapped or proprietary devices failed to load."
                
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM shce_queue WHERE command = ? AND status = 'pending'", (cmd,))
                in_queue = cur.fetchone()[0] > 0
                conn.close()
                
                if not in_queue:
                    shce.handle_failure(
                        command=cmd,
                        error=err_msg,
                        source="optimize_adaptation",
                        auto_queue=True
                    )
    except Exception:
        pass



def system_update_command(engine: Any) -> Optional[dict[str, str]]:
    action = engine.get_action("system_update")
    if not action:
        return None
    return {
        "command": action["command"],
        "risk": action.get("risk", "Medium"),
        "explanation": action.get("explanation", "Update system packages for this OS."),
        "package_manager": detect_os_profile(engine)["package_manager"],
    }
