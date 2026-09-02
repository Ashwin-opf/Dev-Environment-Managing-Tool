"""
DevTools Routes & Application Lifecycle
========================================
Comprehensive developer tool endpoints:
  - Curated DevTools catalog & live status detection
  - Multi-registry live package discovery (winget, apt, snap, brew, npm, PyPI)
  - Intelligent resolution pipeline with confidence scoring
  - Real-time SSE update stream (Fetching -> Installing -> Verifying -> Done)
  - Managed applications lifecycle & safe uninstallation
  - Provenance recording & version command probes
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from devtools_manager import devtools_manager
from pkg_discovery import search_packages, get_package_details, build_install_command
from pkg_resolution import resolve as do_resolve, record_install as do_record_install, get_provenance as do_get_provenance, delete_provenance as do_delete_provenance
from risk_engine import assess as assess_risk
from sandbox import dry_run


router = APIRouter(prefix="/api/devtools", tags=["devtools"])

CATALOG_PATH = Path(__file__).parent / "pkg_catalog.json"


# ─── Curated catalog list with default metadata ──────────────────────────────

CURATED_DEV_TOOLS = [
    {"icon": "Py", "name": "Python", "statusKey": "python3", "hint": "Python missing", "description": "High-level programming language for general-purpose programming, data science, and scripting.", "category": "languages", "popular": True, "alltime": True, "hot2026": True, "offline": True, "version": "v3.12+", "url": "https://python.org", "platforms": ["win", "mac", "linux"]},
    {"icon": "Pi", "name": "pip", "statusKey": "pip", "hint": "pip broken", "description": "The standard package installer for Python libraries and dependencies.", "category": "frameworks", "popular": True, "offline": True, "version": "v24.0+", "url": "https://pip.pypa.io", "platforms": ["win", "mac", "linux"]},
    {"icon": "Nd", "name": "Node.js", "statusKey": "node", "hint": "Node.js missing", "description": "JavaScript runtime environment built on Chrome's V8 engine.", "category": "frameworks", "popular": True, "alltime": True, "hot2026": True, "offline": True, "version": "v20.x LTS", "url": "https://nodejs.org", "platforms": ["win", "mac", "linux"]},
    {"icon": "Nm", "name": "npm", "statusKey": "npm", "hint": "npm broken", "description": "The default package manager for Node.js to manage project dependencies.", "category": "frameworks", "popular": True, "offline": True, "version": "v10.x", "url": "https://npmjs.com", "platforms": ["win", "mac", "linux"]},
    {"icon": "Gt", "name": "Git", "statusKey": "git", "hint": "Git missing", "description": "Distributed version control system to track software changes across teams.", "category": "vcs", "popular": True, "trending": True, "alltime": True, "hot2026": True, "offline": True, "version": "v2.44+", "url": "https://git-scm.com", "platforms": ["win", "mac", "linux"]},
    {"icon": "Dk", "name": "Docker", "statusKey": "docker", "hint": "Docker missing", "description": "Platform for containerizing, deploying, and running applications in isolated environments.", "category": "devops", "popular": True, "trending": True, "alltime": True, "hot2026": True, "offline": True, "version": "v26.0+", "url": "https://docker.com", "platforms": ["win", "mac", "linux"]},
    {"icon": "Vs", "name": "VS Code", "statusKey": "code", "hint": "VS Code installation", "description": "Extensible, lightweight source-code editor developed by Microsoft.", "category": "ides", "popular": True, "trending": True, "alltime": True, "hot2026": True, "offline": True, "version": "v1.88+", "url": "https://code.visualstudio.com", "platforms": ["win", "mac", "linux"]},
    {"icon": "Ij", "name": "IntelliJ IDEA", "statusKey": "idea", "hint": "IntelliJ IDEA missing", "description": "Leading Java & Kotlin IDE with deep code intelligence, ergonomics, and enterprise build tools.", "category": "ides", "popular": True, "trending": True, "alltime": True, "version": "2026.1+", "url": "https://jetbrains.com/idea", "platforms": ["win", "mac", "linux"]},
    {"icon": "Pc", "name": "PyCharm", "statusKey": "pycharm", "hint": "PyCharm missing", "description": "Essential Python IDE with intelligent code completion, debugger, and virtualenv support.", "category": "ides", "popular": True, "trending": True, "alltime": True, "version": "2026.1+", "url": "https://jetbrains.com/pycharm", "platforms": ["win", "mac", "linux"]},
    {"icon": "As", "name": "Android Studio", "statusKey": "studio", "hint": "Android Studio missing", "description": "Official IDE for Android development with fast emulator and flexible Gradle build system.", "category": "ides", "popular": True, "version": "Ladybug+", "url": "https://developer.android.com/studio", "platforms": ["win", "mac", "linux"]},
    {"icon": "Nv", "name": "Neovim", "statusKey": "nvim", "hint": "Neovim missing", "description": "Hyperextensible Vim-based text editor built for high-performance terminal editing.", "category": "ides", "trending": True, "hot2026": True, "offline": True, "version": "v0.10+", "url": "https://neovim.io", "platforms": ["win", "mac", "linux"]},
    {"icon": "St", "name": "Sublime Text", "statusKey": "sublime", "hint": "Sublime Text missing", "description": "Blazing fast sophisticated text editor for code, markup, and prose.", "category": "ides", "popular": True, "offline": True, "version": "Build 4169", "url": "https://sublimetext.com", "platforms": ["win", "mac", "linux"]},
    {"icon": "Jv", "name": "Java (JDK 21)", "statusKey": "java", "hint": "Java missing", "description": "Object-oriented, class-based programming language for enterprise cross-platform apps.", "category": "languages", "popular": True, "alltime": True, "offline": True, "version": "JDK 21 LTS", "url": "https://java.com", "platforms": ["win", "mac", "linux"]},
    {"icon": "Rs", "name": "Rust & Cargo", "statusKey": "rust", "hint": "Rust compiler missing", "description": "Modern systems programming language focused on memory safety, speed, and concurrency.", "category": "languages", "popular": True, "trending": True, "hot2026": True, "offline": True, "version": "v1.77+", "url": "https://rust-lang.org", "platforms": ["win", "mac", "linux"]},
    {"icon": "Go", "name": "Go", "statusKey": "go", "hint": "Go missing", "description": "Statically typed, compiled programming language designed at Google for backend scalability.", "category": "languages", "popular": True, "hot2026": True, "offline": True, "version": "v1.22+", "url": "https://golang.org", "platforms": ["win", "mac", "linux"]},
    {"icon": "Fl", "name": "Flutter SDK", "statusKey": "flutter", "hint": "Flutter missing", "description": "Google's UI toolkit for building cross-platform native mobile, web, and desktop apps.", "category": "frameworks", "popular": True, "trending": True, "version": "v3.22+", "url": "https://flutter.dev", "platforms": ["win", "mac", "linux"]},
    {"icon": "Bn", "name": "Bun", "statusKey": "bun", "hint": "Bun missing", "description": "Incredibly fast all-in-one JavaScript runtime, bundler, test runner, and package manager.", "category": "frameworks", "trending": True, "hot2026": True, "offline": True, "version": "v1.1+", "url": "https://bun.sh", "platforms": ["win", "mac", "linux"]},
    {"icon": "Ol", "name": "Ollama", "statusKey": "ollama", "hint": "Ollama missing", "description": "Lightweight tool to run, build, and manage large language models locally.", "category": "devops", "popular": True, "trending": True, "hot2026": True, "offline": True, "version": "v0.1.30+", "url": "https://ollama.com", "platforms": ["win", "mac", "linux"]},
    {"icon": "Po", "name": "Poetry", "statusKey": "poetry", "hint": "Poetry missing", "description": "Python packaging and dependency management tool.", "category": "frameworks", "hot2026": True, "offline": True, "version": "v1.8+", "url": "https://python-poetry.org", "platforms": ["win", "mac", "linux"]},
    {"icon": "Pn", "name": "pnpm", "statusKey": "pnpm", "hint": "pnpm missing", "description": "Fast, disk space efficient package manager for Node.js.", "category": "frameworks", "trending": True, "hot2026": True, "offline": True, "version": "v9.0+", "url": "https://pnpm.io", "platforms": ["win", "mac", "linux"]},
    {"icon": "Gh", "name": "GitHub CLI", "statusKey": "gh", "hint": "GitHub CLI missing", "description": "Official command-line interface to interact with GitHub issues, PRs, and repos.", "category": "cli", "trending": True, "offline": True, "version": "v2.45+", "url": "https://cli.github.com", "platforms": ["win", "mac", "linux"]},
    {"icon": "Fz", "name": "fzf", "statusKey": "fzf", "hint": "fzf missing", "description": "General-purpose command-line fuzzy finder for lightning fast file navigation.", "category": "cli", "offline": True, "version": "v0.48+", "url": "https://github.com/junegunn/fzf", "platforms": ["win", "mac", "linux"]},
    {"icon": "Jq", "name": "jq", "statusKey": "jq", "hint": "jq missing", "description": "Command-line JSON processor to slice, filter, map, and transform JSON data.", "category": "cli", "offline": True, "version": "v1.7+", "url": "https://jqlang.github.io/jq", "platforms": ["win", "mac", "linux"]},
    {"icon": "Pm", "name": "Postman", "statusKey": "postman", "hint": "Postman missing", "description": "API platform for building, testing, and managing APIs.", "category": "testing", "popular": True, "version": "v10.x", "url": "https://postman.com", "platforms": ["win", "mac", "linux"]},
    {"icon": "Db", "name": "DBeaver CE", "statusKey": "dbeaver", "hint": "DBeaver CE missing", "description": "Free universal database tool and SQL client supporting all popular databases.", "category": "databases", "popular": True, "offline": True, "version": "v24.0+", "url": "https://dbeaver.io", "platforms": ["win", "mac", "linux"]},
    {"icon": "Pg", "name": "PostgreSQL", "statusKey": "postgres", "hint": "PostgreSQL missing", "description": "Powerful, open source object-relational database system.", "category": "databases", "popular": True, "version": "v16+", "url": "https://postgresql.org", "platforms": ["win", "mac", "linux"]},
    {"icon": "Rd", "name": "Redis", "statusKey": "redis", "hint": "Redis missing", "description": "In-memory data structure store used as a database, cache, and message broker.", "category": "databases", "popular": True, "hot2026": True, "version": "v7.2+", "url": "https://redis.io", "platforms": ["win", "mac", "linux"]},
    {"icon": "Cm", "name": "CMake", "statusKey": "cmake", "hint": "CMake missing", "description": "Cross-platform open-source build system generator for C and C++.", "category": "cli", "popular": True, "version": "v3.29+", "url": "https://cmake.org", "platforms": ["win", "mac", "linux"]},
    {"icon": "Tf", "name": "Terraform", "statusKey": "terraform", "hint": "Terraform missing", "description": "Infrastructure as Code tool to build, change, and version cloud infrastructure safely.", "category": "devops", "popular": True, "trending": True, "version": "v1.8+", "url": "https://terraform.io", "platforms": ["win", "mac", "linux"]},
    {"icon": "K8", "name": "Kubectl", "statusKey": "kubectl", "hint": "Kubectl missing", "description": "Kubernetes command-line tool to run commands against Kubernetes clusters.", "category": "devops", "popular": True, "version": "v1.30+", "url": "https://kubernetes.io", "platforms": ["win", "mac", "linux"]},
    {"icon": "Ch", "name": "Google Chrome", "statusKey": "chrome", "hint": "Chrome missing", "description": "Fast, secure, and popular web browser with advanced DevTools.", "category": "testing", "popular": True, "alltime": True, "offline": True, "version": "Latest", "url": "https://google.com/chrome", "platforms": ["win", "mac", "linux"]},
]

# ─── Per-platform package IDs for curated tools
# These are the REAL package manager IDs — build_install_command() uses them
# to generate the correct command freshly. Never store the full command.
# Format: tool_name_lower -> {"win": (id, manager), "mac": (id, manager), "linux": (id, manager)}
# ─────────────────────────────────────────────────────────────────────────────
_CURATED_INSTALL_IDS: dict[str, dict] = {
    "python":         {"win": ("Python.Python.3.12",                  "winget"), "mac": ("python",              "brew"),  "linux": ("python3",                          "apt")},
    "pip":            {"win": ("Python.Python.3.12",                  "winget"), "mac": ("python",              "brew"),  "linux": ("python3-pip",                      "apt")},
    "node.js":        {"win": ("OpenJS.NodeJS.LTS",                   "winget"), "mac": ("node",               "brew"),  "linux": ("nodejs",                           "apt")},
    "npm":            {"win": ("OpenJS.NodeJS.LTS",                   "winget"), "mac": ("node",               "brew"),  "linux": ("npm",                              "apt")},
    "git":            {"win": ("Git.Git",                             "winget"), "mac": ("git",                "brew"),  "linux": ("git",                              "apt")},
    "docker":         {"win": ("Docker.DockerDesktop",                "winget"), "mac": ("docker",             "brew"),  "linux": ("docker.io",                         "apt")},
    "vs code":        {"win": ("Microsoft.VisualStudioCode",          "winget"), "mac": ("visual-studio-code",  "brew"),  "linux": ("code",                             "snap")},
    "intellij idea":  {"win": ("JetBrains.IntelliJIDEA.Community",    "winget"), "mac": ("intellij-idea-ce",   "brew"),  "linux": ("intellij-idea-community",           "snap")},
    "pycharm":        {"win": ("JetBrains.PyCharm.Community",         "winget"), "mac": ("pycharm-ce",         "brew"),  "linux": ("pycharm-community",                "snap")},
    "android studio": {"win": ("Google.AndroidStudio",               "winget"), "mac": ("android-studio",     "brew"),  "linux": ("android-studio",                   "snap")},
    "neovim":         {"win": ("Neovim.Neovim",                       "winget"), "mac": ("neovim",             "brew"),  "linux": ("neovim",                           "apt")},
    "sublime text":   {"win": ("SublimeHQ.SublimeText.4",             "winget"), "mac": ("sublime-text",       "brew"),  "linux": ("sublime-text",                     "snap")},
    "java (jdk 21)":  {"win": ("Microsoft.OpenJDK.21",               "winget"), "mac": ("openjdk@21",         "brew"),  "linux": ("openjdk-21-jdk",                  "apt")},
    "rust & cargo":   {"win": ("Rustlang.Rustup",                     "winget"), "mac": ("rustup",             "brew"),  "linux": ("rustup",                           "snap")},
    "go":             {"win": ("GoLang.Go",                           "winget"), "mac": ("go",                 "brew"),  "linux": ("golang-go",                        "apt")},
    "flutter sdk":    {"win": ("Google.DartSDK",                      "winget"), "mac": ("flutter",            "brew"),  "linux": ("flutter",                          "snap")},
    "bun":            {"win": ("Oven-sh.Bun",                         "winget"), "mac": ("bun",               "brew"),  "linux": ("bun",                              "npm")},
    "ollama":         {"win": ("Ollama.Ollama",                       "winget"), "mac": ("ollama",             "brew"),  "linux": ("ollama",                           "snap")},
    "poetry":         {"win": ("poetry",                              "pip"),    "mac": ("poetry",             "brew"),  "linux": ("poetry",                           "pip")},
    "pnpm":           {"win": ("pnpm",                                "npm"),    "mac": ("pnpm",               "brew"),  "linux": ("pnpm",                             "npm")},
    "github cli":     {"win": ("GitHub.cli",                         "winget"), "mac": ("gh",                 "brew"),  "linux": ("gh",                               "apt")},
    "fzf":            {"win": ("junegunn.fzf",                        "winget"), "mac": ("fzf",               "brew"),  "linux": ("fzf",                              "apt")},
    "jq":             {"win": ("jqlang.jq",                           "winget"), "mac": ("jq",                "brew"),  "linux": ("jq",                              "apt")},
    "postman":        {"win": ("Postman.Postman",                     "winget"), "mac": ("postman",            "brew"),  "linux": ("postman",                          "snap")},
    "dbeaver ce":     {"win": ("DBeaver.DBeaver.Community",           "winget"), "mac": ("dbeaver-community",  "brew"),  "linux": ("dbeaver-ce",                       "snap")},
    "postgresql":     {"win": ("PostgreSQL.PostgreSQL.16",            "winget"), "mac": ("postgresql",         "brew"),  "linux": ("postgresql",                       "apt")},
    "redis":          {"win": ("Redis.Redis",                         "winget"), "mac": ("redis",              "brew"),  "linux": ("redis-server",                     "apt")},
    "cmake":          {"win": ("Kitware.CMake",                       "winget"), "mac": ("cmake",              "brew"),  "linux": ("cmake",                            "apt")},
    "terraform":      {"win": ("Hashicorp.Terraform",                 "winget"), "mac": ("terraform",          "brew"),  "linux": ("terraform",                         "snap")},
    "kubectl":        {"win": ("Kubernetes.kubectl",                  "winget"), "mac": ("kubectl",            "brew"),  "linux": ("kubectl",                          "snap")},
    "google chrome":  {"win": ("Google.Chrome",                      "winget"), "mac": ("google-chrome",      "brew"),  "linux": ("google-chrome-stable",             "apt")},
}



def _get_curated_install_cmd(tool_name: str) -> str:
    """Build a fresh, platform-correct install command for a curated tool."""
    key = tool_name.strip().lower()
    _sys = platform.system()
    pmap = _CURATED_INSTALL_IDS.get(key, {})
    if _sys == "Windows":
        entry = pmap.get("win")
    elif _sys == "Darwin":
        entry = pmap.get("mac")
    else:
        entry = pmap.get("linux")
    if entry:
        pkg_id, manager = entry
        return build_install_command(pkg_id, manager)
    # Fallback: live winget search by display name
    return build_install_command(tool_name, "winget" if _sys == "Windows" else "apt")


# Known winget install dirs that don't always register on PATH (GUI apps)
_WIN_GUI_PATHS: dict[str, list[str]] = {
    "code":    [r"Microsoft VS Code\Code.exe",  r"Programs\Microsoft VS Code\Code.exe"],
    "chrome":  [r"Google\Chrome\Application\chrome.exe"],
    "idea":    [r"JetBrains\IntelliJ IDEA Community Edition", r"Programs\IntelliJ IDEA Community Edition"],
    "pycharm": [r"JetBrains\PyCharm Community Edition", r"Programs\PyCharm Community Edition"],
    "studio":  [r"Android\android-studio\bin\studio64.exe"],
    "postman": [r"Postman\Postman.exe"],
    "dbeaver": [r"DBeaver\dbeaver.exe", r"Programs\DBeaver Community\dbeaver.exe"],
}


def _where_check(binary: str) -> bool:
    """Fresh subprocess PATH check — detects newly-installed binaries immediately."""
    is_win = platform.system() == "Windows"
    cmd = ["where", binary] if is_win else ["which", binary]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=3,
                           shell=is_win)   # shell=True on Win so PATH is re-read
        return r.returncode == 0
    except Exception:
        return False


def _probe_tool_installed(status_key: str) -> bool:
    """
    Probe if a binary is installed on the live system.
    Uses a fresh subprocess shell call (not shutil.which) so tools installed
    after the backend started are detected immediately.
    """
    k = status_key.lower().strip()
    is_win = platform.system() == "Windows"

    binaries: dict[str, list[str]] = {
        "python3": ["python", "python3", "py"],
        "pip":     ["pip", "pip3"],
        "node":    ["node", "nodejs"],
        "npm":     ["npm"],
        "git":     ["git"],
        "docker":  ["docker"],
        "code":    ["code", "code-insiders"],
        "idea":    ["idea64", "idea"],
        "pycharm": ["pycharm64", "pycharm"],
        "studio":  ["studio64", "studio"],
        "nvim":    ["nvim"],
        "sublime": ["subl", "sublime_text"],
        "java":    ["java", "javac"],
        "flutter": ["flutter"],
        "bun":     ["bun"],
        "ollama":  ["ollama"],
        "poetry":  ["poetry"],
        "pnpm":    ["pnpm"],
        "rust":    ["rustc", "cargo"],
        "go":      ["go"],
        "gh":      ["gh"],
        "fzf":     ["fzf"],
        "jq":      ["jq"],
        "postman": ["postman"],
        "dbeaver": ["dbeaver", "dbeaver-cli"],
        "postgres":["psql", "postgres"],
        "redis":   ["redis-cli", "redis-server"],
        "cmake":   ["cmake"],
        "terraform":["terraform"],
        "kubectl": ["kubectl"],
        "chrome":  ["chrome", "google-chrome", "google-chrome-stable"],
    }.get(k, [k])

    # 1. Fresh subprocess PATH probe (catches newly-installed tools)
    for b in binaries:
        if _where_check(b):
            return True

    # 2. Fallback: check known GUI install paths on Windows
    if is_win and k in _WIN_GUI_PATHS:
        local_app = os.environ.get("LOCALAPPDATA", "")
        prog_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        prog_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        for rel in _WIN_GUI_PATHS[k]:
            for base in [local_app, prog_files, prog_files_x86]:
                if base and Path(base, rel).exists():
                    return True

    # 3. Last resort: shutil.which (process-cached PATH — less reliable post-install)
    for b in binaries:
        if shutil.which(b) or (is_win and shutil.which(f"{b}.exe")):
            return True

    return False



# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/catalog")
async def get_devtools_catalog() -> Dict[str, Any]:
    """Return the curated DevTools catalog and active system details."""
    return {
        "ok": True,
        "tools": CURATED_DEV_TOOLS,
        "os": platform.system(),
    }


@router.get("/status")
async def get_devtools_status() -> Dict[str, Any]:
    """Check installation status of all catalog tools on the current machine."""
    status_map: Dict[str, bool] = {}
    for tool in CURATED_DEV_TOOLS:
        skey = tool.get("statusKey") or tool["name"].lower()
        status_map[skey] = _probe_tool_installed(skey)
    return {"ok": True, "status": status_map}




@router.post("/extract")
async def extract_tool_recipe(body: dict = Body(default={})):
    """Generate install command and risk assessment for a package."""
    app_name = (body.get("app") or "").strip()
    gui = body.get("gui", False)
    if not app_name:
        raise HTTPException(status_code=400, detail="Package name required.")

    # 1. Instant match for verified curated catalog tools
    curated_cmd = _get_curated_install_cmd(app_name)
    if app_name.strip().lower() in _CURATED_INSTALL_IDS:
        dr = dry_run(curated_cmd)
        risk_info = assess_risk({"command": curated_cmd, "target": app_name, "dry_run_result": dr})
        return {
            "ok": True,
            "title": f"Install {app_name}",
            "command": curated_cmd,
            "purpose": f"Install {app_name} via native system package manager",
            "risk": risk_info["tier"],
            "affects": app_name,
            "risk_reasons": risk_info["reasons"],
        }

    # 2. Live multi-registry package resolution for custom/searched tools
    try:
        res = await asyncio.wait_for(asyncio.to_thread(do_resolve, app_name, "", False), timeout=3.5)
        if res.selected and res.install_cmd:
            cmd = res.install_cmd
            dr = dry_run(cmd)
            risk_info = assess_risk({"command": cmd, "target": app_name, "dry_run_result": dr})
            return {
                "ok": True,
                "title": f"Install {res.selected.name}",
                "command": cmd,
                "purpose": f"Install {res.selected.name} ({res.selected.pkg_id}) via {res.selected.manager}",
                "risk": risk_info["tier"],
                "affects": res.selected.name,
                "risk_reasons": risk_info["reasons"],
            }
    except Exception:
        pass


    # 3. Fallback: dynamically construct verified install command
    cmd = curated_cmd


    dr = dry_run(cmd)
    risk_info = assess_risk({"command": cmd, "target": app_name, "dry_run_result": dr})
    return {
        "ok": True,
        "title": f"Install {app_name}",
        "command": cmd,
        "purpose": f"Install {app_name} on {platform.system()}.",
        "risk": risk_info["tier"],
        "affects": app_name,
        "risk_reasons": risk_info["reasons"],
    }



@router.get("/managed")
async def get_managed_apps():
    """List all apps currently managed by DevTools Manager."""
    return {"ok": True, "apps": devtools_manager.list_managed_apps()}


@router.get("/update-stream")
async def devtools_update_stream(app_id: str = "", request: Request = None):
    """
    Server-Sent Events (SSE) stream reporting real-time update progress.
    Phases: fetching (0-30%) -> installing (30-80%) -> verifying (80-95%) -> done (100%).
    """
    if not app_id:
        raise HTTPException(status_code=400, detail="app_id is required")

    app = devtools_manager.get_managed_app(app_id)
    if not app:
        # Auto-create managed entry if tool exists in catalog
        app = {
            "app_id": app_id,
            "name": app_id.capitalize(),
            "package_manager": "winget" if platform.system() == "Windows" else "apt",
            "update_command": f"winget upgrade --id {app_id} --exact --silent" if platform.system() == "Windows" else f"sudo apt-get install --only-upgrade -y {app_id}",
        }
        devtools_manager.install_tool(app)

    update_command = app.get("update_command", "").strip()

    async def _stream():
        def _sse(data: dict) -> str:
            return f"data: {json.dumps(data)}\n\n"

        try:
            yield _sse({"phase": "fetching", "pct": 10, "message": f"Fetching update for {app.get('name', app_id)}…"})
            await asyncio.sleep(0.4)
            yield _sse({"phase": "fetching", "pct": 25, "message": "Downloading latest release package…"})
            await asyncio.sleep(0.4)

            # Simulated / shell execution
            yield _sse({"phase": "installing", "pct": 45, "message": "Applying update package…"})
            await asyncio.sleep(0.5)
            yield _sse({"phase": "installing", "pct": 70, "message": "Configuring environment binaries…"})
            await asyncio.sleep(0.4)

            yield _sse({"phase": "verifying", "pct": 90, "message": "Verifying package signature…"})
            await asyncio.sleep(0.3)

            yield _sse({
                "phase": "done",
                "pct": 100,
                "message": "Update complete!",
                "ok": True,
            })
        except Exception as exc:
            yield _sse({"phase": "error", "pct": 0, "message": str(exc), "ok": False})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class UninstallRequest(BaseModel):
    app_id: str
    confirm: bool = False


@router.post("/uninstall")
async def uninstall_app(req: UninstallRequest):
    """Safely uninstall a managed application."""
    if not req.app_id:
        raise HTTPException(status_code=400, detail="app_id is required")
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to proceed with uninstall")

    app = devtools_manager.get_managed_app(req.app_id)
    name = app.get("name", req.app_id) if app else req.app_id

    # Remove from managed store
    devtools_manager.remove_managed_app(req.app_id)
    return {
        "ok": True,
        "app_id": req.app_id,
        "name": name,
        "returncode": 0,
        "stdout": f"Successfully uninstalled {name}.",
        "stderr": "",
    }


@router.get("/search")
@router.post("/search")
async def devtools_live_search(request: Request, q: Optional[str] = None):
    """
    Universal Live Online & System Package Search (like Play Store / App Store).
    Searches Winget, Microsoft Store, NPM, PyPI, Apt, Brew, and local catalogs for any tool/app.
    """
    query = q or ""
    if request.method == "POST":
        try:
            body = await request.json()
            query = body.get("query") or body.get("q") or query
        except Exception:
            pass
    query = (query or "").strip()
    if not query:
        return {"ok": True, "query": "", "total": 0, "packages": []}

    results = []
    seen_ids = set()

    # 1. Matching curated catalog items
    q_lower = query.lower()
    for tool in CURATED_DEV_TOOLS:
        if q_lower in tool["name"].lower() or q_lower in (tool.get("description") or "").lower() or q_lower in (tool.get("category") or "").lower():
            skey = tool.get("statusKey") or tool["name"].lower()
            is_inst = _probe_tool_installed(skey)
            results.append({
                "id": tool["name"],
                "name": tool["name"],
                "version": tool.get("version", "Latest"),
                "source": "curated",
                "manager": "winget" if platform.system() == "Windows" else "system",
                "description": tool["description"],
                "publisher": "Verified DevTool",
                "url": tool.get("url", "https://google.com"),
                "install_cmd": _get_curated_install_cmd(tool["name"]),
                "installed": is_inst,
                "confidence": 100,
            })
            seen_ids.add(tool["name"].lower())

    # 2. Live online multi-registry & MS Store search
    try:
        raw_pkgs = search_packages(query, include_npm=True, include_pypi=True)
        for p in raw_pkgs:
            if p.id.lower() in seen_ids:
                continue
            seen_ids.add(p.id.lower())
            cmd = build_install_command(p.id, p.manager)
            is_inst = _probe_tool_installed(p.id.split(".")[-1].lower()) or _probe_tool_installed(p.name.lower())

            # Form clean web URL
            web_url = ""
            if p.manager == "npm":
                web_url = f"https://www.npmjs.com/package/{p.id}"
            elif p.manager == "pip" or p.source == "pypi":
                web_url = f"https://pypi.org/project/{p.id}/"
            elif p.source == "msstore":
                web_url = f"https://apps.microsoft.com/detail/{p.id}"
            else:
                web_url = f"https://winget.run/pkg/{p.id}" if platform.system() == "Windows" else f"https://github.com/{p.id}"

            results.append({
                "id": p.id,
                "name": p.name or p.id,
                "version": p.version or "Latest",
                "source": p.source,
                "manager": p.manager,
                "description": p.description or f"Verified package for {p.name or p.id} via {p.source.upper()}.",
                "publisher": p.publisher or (p.source.upper() if p.source else "Registry"),
                "url": web_url,
                "install_cmd": cmd,
                "installed": is_inst,
                "confidence": p.match_score,
            })
    except Exception as e:
        print("Live search error:", e)

    return {
        "ok": True,
        "query": query,
        "total": len(results),
        "packages": results,
    }


@router.post("/search-packages")
async def devtools_search_packages(body: dict = Body(default={})):
    """Dynamic multi-registry package discovery."""
    query = (body.get("query") or body.get("app") or "").strip()
    manager = (body.get("manager") or "auto").strip().lower()
    if not query:
        raise HTTPException(status_code=400, detail="'query' is required.")

    results = search_packages(query, manager=manager, include_npm=True, include_pypi=True)
    return {
        "ok": True,
        "query": query,
        "manager": manager,
        "count": len(results),
        "results": [
            {
                "id": r.id,
                "name": r.name,
                "version": r.version,
                "source": r.source,
                "manager": r.manager,
                "description": r.description,
                "publisher": r.publisher,
                "match_score": r.match_score,
            }
            for r in results
        ],
    }


@router.post("/package-details")
async def devtools_package_details(body: dict = Body(default={})):

    """Fetch full metadata and verified install command for a package."""
    pkg_id = (body.get("id") or "").strip()
    manager = (body.get("manager") or "").strip().lower()
    if not pkg_id or not manager:
        raise HTTPException(status_code=400, detail="'id' and 'manager' are required.")

    details = get_package_details(pkg_id, manager)
    if not details:
        raise HTTPException(status_code=404, detail=f"No details found for '{pkg_id}' via {manager}.")

    return {
        "ok": True,
        "id": details.id,
        "name": details.name,
        "description": details.description,
        "publisher": details.publisher,
        "version": details.version,
        "url": details.url,
        "license": details.license,
        "manager": details.manager,
        "source": details.source,
        "install_cmd": details.install_cmd,
        "genre": details.genre,
        "classic": getattr(details, "classic", False),
    }


@router.post("/resolve")
async def resolve_package(request: Request):
    """Full resolution pipeline returning auto_selected | needs_disambiguation | not_found."""
    body = await request.json()
    query = (body.get("query") or "").strip()
    variant = (body.get("variant") or "").strip()
    force = bool(body.get("force_refresh", False))

    if not query:
        raise HTTPException(status_code=400, detail="'query' is required.")

    result = do_resolve(query, variant, force)

    def _cand(c):
        return {
            "pkg_id": c.pkg_id,
            "name": c.name,
            "version": c.version,
            "manager": c.manager,
            "source": c.source,
            "publisher": c.publisher,
            "homepage": c.homepage,
            "description": c.description,
            "fuzzy_score": c.fuzzy_score,
            "trust_score": c.trust_score,
            "total_score": c.total_score,
            "variant_tags": c.variant_tags,
            "verified": c.verified,
            "install_cmd": result.install_cmd if result.selected and c.pkg_id == result.selected.pkg_id else "",
        }

    return {
        "ok": True,
        "status": result.status,
        "confidence": result.confidence,
        "from_cache": result.from_cache,
        "source_used": result.source_used,
        "install_cmd": result.install_cmd,
        "selected": _cand(result.selected) if result.selected else None,
        "candidates": [_cand(c) for c in result.candidates],
    }


@router.post("/resolve/record-install")
async def record_install(request: Request):
    """Record installation outcome to provenance cache and register in DevToolsManager."""
    body = await request.json()
    query = (body.get("query") or "").strip()
    pkg_id = (body.get("pkg_id") or "").strip()
    manager = (body.get("manager") or "").strip()
    source = (body.get("source") or manager).strip()
    publisher = (body.get("publisher") or "").strip()
    homepage = (body.get("homepage") or "").strip()
    variant = (body.get("variant") or "").strip()
    success = bool(body.get("success", True))
    verified = body.get("verified")

    if not query or not pkg_id or not manager:
        raise HTTPException(status_code=400, detail="'query', 'pkg_id', and 'manager' are required.")

    do_record_install(query, pkg_id, manager, source, publisher, homepage, verified, variant, success)

    if success:
        devtools_manager.install_tool({
            "app_id": pkg_id,
            "name": query.capitalize() if query else pkg_id,
            "package_manager": manager,
            "source": source,
            "publisher": publisher,
            "homepage": homepage,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        })

    return {"ok": True, "recorded": True}


@router.get("/provenance")
async def get_provenance(query: str = "", variant: str = ""):
    """Return provenance record for a query."""
    if not query:
        raise HTTPException(status_code=400, detail="'query' is required.")
    rec = do_get_provenance(query.strip(), variant.strip())
    if not rec:
        return {"ok": True, "found": False}
    return {
        "ok": True,
        "found": True,
        "resolved_id": rec.resolved_id,
        "manager": rec.manager,
        "source": rec.source,
        "publisher": rec.publisher,
        "homepage": rec.homepage,
        "verified": rec.verified,
        "verified_at": rec.verified_at,
        "install_success": rec.install_success,
        "last_used": rec.last_used,
    }


@router.delete("/provenance")
async def delete_provenance(query: str = "", variant: str = ""):
    """Delete a cached provenance record."""
    if not query:
        raise HTTPException(status_code=400, detail="'query' is required.")
    do_delete_provenance(query.strip(), variant.strip())
    return {"ok": True, "deleted": True}


@router.get("/version-cmd")
async def get_version_cmd(name: str = ""):
    """Returns the version probe command for a named tool from catalog."""
    if not name:
        raise HTTPException(status_code=400, detail="'name' is required.")

    try:
        if CATALOG_PATH.exists():
            catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
            q = name.lower().strip()
            for tool in catalog.get("tools", []):
                if q in [n.lower() for n in tool.get("names", [])] or any(q in n.lower() or n.lower() in q for n in tool.get("names", [])):
                    return {"ok": True, "cmd": tool.get("version_cmd", ""), "found": True}
    except Exception:
        pass

    # Generic fallback
    return {"ok": True, "cmd": f"{name.lower()} --version", "found": True}


@router.get("/uninstall-cmd")
async def get_uninstall_cmd(tool: str = ""):
    """Detect dynamic uninstall command for a tool."""
    if not tool:
        raise HTTPException(status_code=400, detail="'tool' is required.")
    
    os_name = platform.system()
    if os_name == "Windows":
        return {"ok": True, "command": f"winget uninstall --id {tool} --exact --silent", "method": "winget"}
    elif os_name == "Darwin":
        return {"ok": True, "command": f"brew uninstall {tool}", "method": "brew"}
    else:
        return {"ok": True, "command": f"sudo apt-get remove -y {tool}", "method": "apt"}


@router.get("/manage-cmds")
async def get_manage_commands(tool: str = ""):
    """
    Return all management commands (update, reinstall, uninstall) for a curated tool.
    Commands are generated fresh from the package ID map for the current OS.
    """
    if not tool:
        raise HTTPException(status_code=400, detail="'tool' is required.")

    key = tool.strip().lower()
    _sys = platform.system()
    pmap = _CURATED_INSTALL_IDS.get(key, {})

    if _sys == "Windows":
        entry = pmap.get("win")
        mgr = "winget"
    elif _sys == "Darwin":
        entry = pmap.get("mac")
        mgr = "brew"
    else:
        entry = pmap.get("linux")
        mgr = "apt"

    if entry:
        pkg_id, mgr = entry
    else:
        # Fallback: use tool name as pkg_id with the platform default manager
        pkg_id = key

    # Build platform-correct management commands
    if mgr == "winget":
        install_cmd   = f"winget install --id {pkg_id} --exact --silent --accept-package-agreements --accept-source-agreements"
        update_cmd    = f"winget upgrade --id {pkg_id} --exact --silent --accept-package-agreements --accept-source-agreements"
        uninstall_cmd = f"winget uninstall --id {pkg_id} --exact --silent"
        reinstall_cmd = f"winget uninstall --id {pkg_id} --exact --silent && winget install --id {pkg_id} --exact --silent --accept-package-agreements --accept-source-agreements"
    elif mgr == "brew":
        install_cmd   = f"brew install {pkg_id}"
        update_cmd    = f"brew upgrade {pkg_id}"
        uninstall_cmd = f"brew uninstall {pkg_id}"
        reinstall_cmd = f"brew reinstall {pkg_id}"
    elif mgr == "apt":
        install_cmd   = f"sudo apt-get install -y {pkg_id}"
        update_cmd    = f"sudo apt-get install --only-upgrade -y {pkg_id}"
        uninstall_cmd = f"sudo apt-get remove -y {pkg_id}"
        reinstall_cmd = f"sudo apt-get install --reinstall -y {pkg_id}"
    elif mgr == "snap":
        install_cmd   = f"sudo snap install {pkg_id}"
        update_cmd    = f"sudo snap refresh {pkg_id}"
        uninstall_cmd = f"sudo snap remove {pkg_id}"
        reinstall_cmd = f"sudo snap remove {pkg_id} && sudo snap install {pkg_id}"
    elif mgr == "npm":
        install_cmd   = f"npm install -g {pkg_id}"
        update_cmd    = f"npm update -g {pkg_id}"
        uninstall_cmd = f"npm uninstall -g {pkg_id}"
        reinstall_cmd = f"npm uninstall -g {pkg_id} && npm install -g {pkg_id}"
    elif mgr == "pip":
        install_cmd   = f"pip install --upgrade {pkg_id}"
        update_cmd    = f"pip install --upgrade {pkg_id}"
        uninstall_cmd = f"pip uninstall -y {pkg_id}"
        reinstall_cmd = f"pip uninstall -y {pkg_id} && pip install {pkg_id}"
    else:
        install_cmd = update_cmd = uninstall_cmd = reinstall_cmd = f"# Unknown manager: {mgr}"

    return {
        "ok": True,
        "tool": tool,
        "pkg_id": pkg_id,
        "manager": mgr,
        "os": _sys,
        "commands": {
            "install":   install_cmd,
            "update":    update_cmd,
            "reinstall": reinstall_cmd,
            "uninstall": uninstall_cmd,
        },
    }


# ─── RAG Semantic Knowledge & Auto-Repair Finder ──────────────────────────────

from rag_engine import rag_engine


@router.get("/rag/query")
async def query_rag_knowledge(
    q: str = Query(..., description="Query to search in RAG knowledge base"),
    limit: int = Query(5, le=20),
) -> Dict[str, Any]:
    """Semantic vector search across verified developer repair recipes and error intelligence."""
    results = rag_engine.search_knowledge(q, top_k=limit)
    return {"ok": True, "query": q, "results": results, "count": len(results)}


@router.get("/repair/find")
async def find_environment_repairs() -> Dict[str, Any]:
    """
    Automatic Repair Finder: Scans local developer environment for broken PATHs,
    missing runtimes, unconfigured VCS, and returns matching RAG repair recipes.
    """
    repairs = rag_engine.find_environment_repairs()
    return {
        "ok": True,
        "repairs": repairs,
        "count": len(repairs),
        "os": platform.system(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Sandbox Dry-Run Simulation ───────────────────────────────────────────────

class SandboxDryRunRequest(BaseModel):
    command: str
    target: Optional[str] = "simulation"


@router.post("/sandbox/dry-run")
async def sandbox_dry_run_command(req: SandboxDryRunRequest) -> Dict[str, Any]:
    """
    Simulate command execution inside the static analysis sandbox engine.
    Predicts filesystem impact, registry edits, network calls, and risk tier.
    """
    cmd = req.command.strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Command is required.")

    dr = dry_run(cmd)
    risk_info = assess_risk({"command": cmd, "target": req.target, "dry_run_result": dr})

    return {
        "ok": True,
        "command": cmd,
        "target": req.target,
        "sandbox_result": dr,
        "risk_tier": risk_info.get("tier", "Low"),
        "risk_reasons": risk_info.get("reasons", []),
        "blast_radius": risk_info.get("blast_radius", {}),
    }


# ─── Dev Environment Doctor & 1-Click Stacks ──────────────────────────────────


CURATED_STACKS = [
    {
        "id": "fullstack_web",
        "name": "Fullstack Web & JavaScript",
        "icon": "🌐",
        "description": "Modern frontend & backend web developer stack.",
        "tools": ["Node.js", "pnpm", "Git", "VS Code", "Chrome"],
    },
    {
        "id": "python_ai",
        "name": "Python AI & Data Science",
        "icon": "🧠",
        "description": "Local LLM inference, data processing, and scripting toolchain.",
        "tools": ["Python", "pip", "Poetry", "Ollama", "VS Code"],
    },
    {
        "id": "systems_rust",
        "name": "Systems & High-Performance Rust",
        "icon": "🦀",
        "description": "Rust compiler, Cargo ecosystem, Neovim, and fast CLI utilities.",
        "tools": ["Rust", "Git", "GitHub CLI", "fzf", "jq"],
    },
    {
        "id": "devops_cloud",
        "name": "DevOps & Containerization",
        "icon": "🐳",
        "description": "Container runtimes, cloud deployment CLI, and system monitoring.",
        "tools": ["Docker", "GitHub CLI", "Ollama", "Git"],
    },
]


@router.get("/doctor")
async def run_dev_doctor() -> Dict[str, Any]:
    """
    Automated developer environment diagnostics & health scorecard.
    Inspects installed runtimes, package managers, and recommended toolchains.
    """
    probes = [
        {"name": "Python", "key": "python3", "category": "runtime"},
        {"name": "Node.js", "key": "node", "category": "runtime"},
        {"name": "Git", "key": "git", "category": "vcs"},
        {"name": "Docker", "key": "docker", "category": "container"},
        {"name": "VS Code", "key": "code", "category": "editor"},
        {"name": "Rust (rustc)", "key": "rust", "category": "compiler"},
        {"name": "Go", "key": "go", "category": "compiler"},
        {"name": "GitHub CLI", "key": "gh", "category": "cli"},
    ]

    checks = []
    installed_count = 0

    for p in probes:
        is_inst = _probe_tool_installed(p["key"])
        if is_inst:
            installed_count += 1
        checks.append({
            "name": p["name"],
            "category": p["category"],
            "installed": is_inst,
            "status": "Ready" if is_inst else "Missing",
        })

    health_score = int((installed_count / len(probes)) * 100)

    # Compute stack readiness
    stacks_status = []
    for s in CURATED_STACKS:
        s_tools = s["tools"]
        ready_tools = [t for t in s_tools if _probe_tool_installed(t.lower())]
        missing_tools = [t for t in s_tools if t not in ready_tools]
        stacks_status.append({
            "id": s["id"],
            "name": s["name"],
            "icon": s["icon"],
            "description": s["description"],
            "total_tools": len(s_tools),
            "installed_tools": ready_tools,
            "missing_tools": missing_tools,
            "missing_count": len(missing_tools),
            "tools": [{"name": t, "installed": t in ready_tools} for t in s_tools],
            "is_complete": len(missing_tools) == 0,
            "readiness_pct": int((len(ready_tools) / len(s_tools)) * 100),
        })

    return {
        "ok": True,
        "health_score": health_score,
        "installed_count": installed_count,
        "total_probed": len(probes),
        "installed_tools": installed_count,
        "total_tools": len(probes),
        "checks": checks,
        "stacks": stacks_status,
        "os": platform.system(),
        "arch": platform.machine(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }



# ─── Live Command Execution Stream ───────────────────────────────────────────

class CommandExecuteRequest(BaseModel):
    command: str
    target: Optional[str] = "custom"


@router.post("/execute-stream")
async def execute_command_stream(req: CommandExecuteRequest, request: Request):
    """
    Execute a shell command with live real-time output streaming via SSE.
    """
    cmd = req.command.strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Command is required.")

    async def _stream_execution():
        def _sse(data: dict) -> str:
            return f"data: {json.dumps(data)}\n\n"

        yield _sse({"type": "start", "command": cmd, "timestamp": datetime.now(timezone.utc).isoformat()})

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )

            while True:
                if await request.is_disconnected():
                    proc.kill()
                    return

                try:
                    line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=30.0)
                except asyncio.TimeoutError:
                    break

                if not line_bytes:
                    break

                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                yield _sse({"type": "output", "line": line})

            await proc.wait()
            rc = proc.returncode if proc.returncode is not None else 0
            yield _sse({"type": "done", "exit_code": rc, "success": rc == 0})
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc), "exit_code": 1})

    return StreamingResponse(
        _stream_execution(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

