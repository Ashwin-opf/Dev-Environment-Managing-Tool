"""
Repair Engine â€“ Rule-based command executor
Maps issues to verified repair recipes from SQLite, validates safety,
and executes commands only after user approval.
"""
import platform
import sqlite3
import subprocess
import shutil
import json
import os
import socket
import time
import urllib.request
from pathlib import Path
from typing import Optional


# Cross-platform subprocess wrapper – always decodes output as UTF-8.
# Prevents UnicodeDecodeError on Windows where cmd/PowerShell defaults to cp1252.
def _safe_run(
    cmd,
    *,
    shell: bool = False,
    timeout: int = 10,
    cwd=None,
    **kwargs,
) -> subprocess.CompletedProcess:
    run_kwargs = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "cwd": cwd,
        "shell": shell,
    }
    run_kwargs.update(kwargs)
    return subprocess.run(cmd, **run_kwargs)


CATALOG_REFRESH_SECONDS = 6 * 60 * 60

DEFAULT_COMMAND_CATALOG = {
    "version": 1,
    "actions": {
        "temp_cleanup": {
            "Windows": {
                "command": 'del /q/f/s "%TEMP%\\*" 2>nul & del /q/f/s "%TMP%\\*" 2>nul',
                "risk": "Low",
                "explanation": "Deletes all files in the Windows TEMP and TMP directories.",
            },
            "Linux": {
                "command": "find /tmp -mindepth 1 -user $(whoami) -depth -delete 2>/dev/null || true && rm -rf ~/.cache/thumbnails/*",
                "risk": "Low",
                "explanation": "Removes user-owned temporary files and thumbnail cache.",
            },
            "Darwin": {
                "command": "rm -rf \"$TMPDIR\"* ~/Library/Caches/com.apple.Safari/* 2>/dev/null || true",
                "risk": "Low",
                "explanation": "Removes user temporary files and Safari cache on macOS.",
            },
        },
        "browser_cache_cleanup": {
            "Windows": {
                "command": 'del /q/f/s "%LOCALAPPDATA%\\Google\\Chrome\\User Data\\Default\\Cache\\*" 2>nul',
                "risk": "Low",
                "explanation": "Deletes the Chrome cache folder on Windows.",
            },
            "Linux": {
                "command": "rm -rf ~/.cache/google-chrome/ ~/.cache/chromium/ ~/.cache/mozilla/",
                "risk": "Low",
                "explanation": "Clears common browser cache directories on Linux.",
            },
            "Darwin": {
                "command": "rm -rf ~/Library/Caches/Google/Chrome/Default/Cache ~/Library/Caches/org.mozilla.firefox ~/Library/Caches/com.apple.Safari 2>/dev/null || true",
                "risk": "Low",
                "explanation": "Clears common browser cache directories on macOS.",
            },
        },
        "boost_ram": {
            "Linux": {
                "command": "sync && echo 3 | sudo tee /proc/sys/vm/drop_caches",
                "risk": "Medium",
                "explanation": "Flushes Linux filesystem caches to free memory.",
            },
            "Windows": {
                "command": 'powershell -Command "Get-Process | Where-Object { $_.WorkingSet -gt 500MB } | Format-Table Name,Id,WorkingSet -AutoSize"',
                "risk": "Low",
                "explanation": "Lists high-memory Windows processes so the user can decide what to close.",
            },
            "Darwin": {
                "command": "purge",
                "risk": "Medium",
                "explanation": "Asks macOS to purge inactive disk cache memory.",
            },
        },
        "startup_list": {
            "Windows": {
                "command": 'powershell -Command "Get-CimInstance Win32_StartupCommand | Select-Object Name,Command | Format-Table -AutoSize"',
                "risk": "Low",
                "explanation": "Lists Windows startup programs.",
            },
            "Linux": {
                "command": "systemctl list-unit-files --state=enabled --type=service",
                "risk": "Low",
                "explanation": "Lists enabled Linux systemd services.",
            },
            "Darwin": {
                "command": "osascript -e 'tell application \"System Events\" to get the name of every login item'",
                "risk": "Low",
                "explanation": "Lists macOS login items.",
            },
        },
        "system_update": {
            "Windows": {
                "command": "winget upgrade --all --silent",
                "risk": "Medium",
                "explanation": "Updates installed packages through Winget.",
            },
            "Linux": {
                "debian": "sudo apt update && sudo apt upgrade -y",
                "fedora": "sudo dnf upgrade -y",
                "arch": "sudo pacman -Syu --noconfirm",
                "opensuse": "sudo zypper refresh && sudo zypper update -y",
                "command": "sudo apt update && sudo apt upgrade -y",
                "risk": "Medium",
                "explanation": "Downloads package lists and upgrades installed packages using the native package manager.",
            },
            "Darwin": {
                "command": "softwareupdate -ia && (brew update && brew upgrade || true)",
                "risk": "Medium",
                "explanation": "Installs macOS software updates and updates Homebrew packages when Homebrew is installed.",
            },
        },
        "remove_orphans": {
            "Linux": {
                "debian": "sudo apt-get autoremove -y && sudo apt-get autoclean",
                "fedora": "sudo dnf autoremove -y",
                "arch": "sudo pacman -Rns $(pacman -Qtdq) --noconfirm 2>/dev/null || true",
                "opensuse": "sudo zypper packages --unneeded && sudo zypper clean --all",
                "command": "sudo apt-get autoremove -y && sudo apt-get autoclean",
                "risk": "Low",
                "explanation": "Removes packages that are no longer needed.",
            },
            "Darwin": {
                "command": "brew autoremove && brew cleanup",
                "risk": "Low",
                "explanation": "Removes unused Homebrew dependencies and cached files.",
            },
        },
        "driver_package_update": {
            "Linux": {
                "debian": "sudo apt-get update && sudo apt-get install --only-upgrade -y linux-firmware linux-generic linux-generic-hwe-24.04",
                "fedora": "sudo dnf upgrade -y linux-firmware kernel kernel-core kernel-modules",
                "arch": "sudo pacman -Syu --noconfirm linux-firmware linux",
                "command": "sudo apt-get update && sudo apt-get install --only-upgrade -y linux-firmware linux-generic linux-generic-hwe-24.04",
                "risk": "Medium",
                "explanation": "Updates firmware and kernel driver packages without unloading active modules. Reboot after completion.",
            },
            "Windows": {
                "command": "winget upgrade --all --silent",
                "risk": "Medium",
                "explanation": "Updates installed vendor driver tools and packages managed by Winget.",
            },
            "Darwin": {
                "command": "softwareupdate -ia",
                "risk": "Medium",
                "explanation": "Installs macOS updates, including Apple-provided driver and firmware updates.",
            },
        },
        "driver_package_check": {
            "Linux": {
                "debian": "apt-get -o DPkg::Lock::Timeout=1 -s install --only-upgrade -y linux-firmware linux-generic linux-generic-hwe-24.04",
                "fedora": "dnf check-update linux-firmware kernel kernel-core kernel-modules",
                "arch": "checkupdates 2>/dev/null | grep -E '^(linux|linux-firmware)\\b' || true",
                "command": "apt-get -o DPkg::Lock::Timeout=1 -s install --only-upgrade -y linux-firmware linux-generic linux-generic-hwe-24.04",
                "risk": "Low",
                "explanation": "Checks whether firmware or kernel driver package updates are available.",
            },
            "Windows": {
                "command": "winget upgrade",
                "risk": "Low",
                "explanation": "Checks whether driver or application updates are available through Winget.",
            },
            "Darwin": {
                "command": "softwareupdate -l",
                "risk": "Low",
                "explanation": "Checks whether macOS software, firmware, or driver updates are available.",
            },
        },
    },
}

ACTION_RECIPE_TITLES = {
    "temp_cleanup": "Clear temporary files",
    "browser_cache_cleanup": "Browser cache cleanup",
    "boost_ram": "Boost RAM",
    "startup_list": "Slow startup",
    "remove_orphans": "Remove Orphan Packages",
}


class RepairEngine:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.os_name = platform.system()   # "Windows" or "Linux"
        self.distro = self._detect_distro()
        self.catalog_path = self.db_path.with_name("command_catalog_cache.json")
        self.command_catalog = self._load_command_catalog()
        self._ensure_db()

    def _detect_distro(self) -> str:
        if self.os_name == "Darwin":
            return "darwin"
        if self.os_name != "Linux":
            return "windows"
        try:
            release_info = platform.freedesktop_os_release()
            dist_id = release_info.get("ID", "").lower()
            id_like = release_info.get("ID_LIKE", "").lower()
            if "arch" in dist_id or "arch" in id_like:
                return "arch"
            if "opensuse" in dist_id or "suse" in dist_id or "opensuse" in id_like or "suse" in id_like:
                return "opensuse"
            if "fedora" in dist_id or "fedora" in id_like or "rhel" in dist_id or "centos" in dist_id or "nobara" in dist_id:
                return "fedora"
            if "arch" in dist_id or "garuda" in dist_id or "manjaro" in dist_id:
                return "arch"
            if "debian" in dist_id or "ubuntu" in dist_id or "zorin" in dist_id or "mint" in dist_id or "kali" in dist_id or "debian" in id_like or "ubuntu" in id_like:
                return "debian"
        except Exception:
            pass
        
        if shutil.which("zypper"):
            return "opensuse"
        if shutil.which("apt-get") or shutil.which("apt"):
            return "debian"
        if shutil.which("dnf"):
            return "fedora"
        if shutil.which("pacman"):
            return "arch"
        return "debian"

    def _merge_catalog(self, base: dict, override: dict) -> dict:
        def merge_dict(left: dict, right: dict) -> dict:
            result = json.loads(json.dumps(left))
            for key, value in (right or {}).items():
                if isinstance(value, dict) and isinstance(result.get(key), dict):
                    result[key] = merge_dict(result[key], value)
                else:
                    result[key] = value
            return result

        return merge_dict(base, override or {})

    def _load_cached_catalog(self) -> dict:
        try:
            if self.catalog_path.exists():
                return json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _remote_catalog_stale(self) -> bool:
        try:
            if not self.catalog_path.exists():
                return True
            return time.time() - self.catalog_path.stat().st_mtime > CATALOG_REFRESH_SECONDS
        except Exception:
            return True

    def _fetch_remote_catalog(self, force: bool = False) -> Optional[dict]:
        url = os.getenv("PC_DOCTOR_COMMAND_CATALOG_URL", "").strip()
        if not url:
            return None
        if not force and not self._remote_catalog_stale():
            return None
        if not self._check_internet():
            return None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PC-Doctor/1.0"})
            with urllib.request.urlopen(req, timeout=8) as response:
                if response.status >= 400:
                    return None
                payload = response.read(512 * 1024).decode("utf-8")
            catalog = json.loads(payload)
            if not isinstance(catalog, dict) or not isinstance(catalog.get("actions"), dict):
                return None
            self.catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
            return catalog
        except Exception:
            return None

    def _load_command_catalog(self) -> dict:
        cached = self._load_cached_catalog()
        remote = self._fetch_remote_catalog()
        return self._merge_catalog(DEFAULT_COMMAND_CATALOG, remote or cached)

    def refresh_command_catalog(self, force: bool = False) -> dict:
        remote = self._fetch_remote_catalog(force=force)
        if remote:
            self.command_catalog = self._merge_catalog(DEFAULT_COMMAND_CATALOG, remote)
            return {"updated": True, "source": "remote", "catalog": self.command_catalog}
        cached = self._load_cached_catalog()
        self.command_catalog = self._merge_catalog(DEFAULT_COMMAND_CATALOG, cached)
        return {"updated": False, "source": "cache" if cached else "defaults", "catalog": self.command_catalog}

    def get_action(self, key: str, os_name: Optional[str] = None) -> Optional[dict]:
        os_name = os_name or self.os_name
        action = self.command_catalog.get("actions", {}).get(key)
        if not isinstance(action, dict):
            return None
        entry = action.get(os_name)
        if not isinstance(entry, dict):
            return None
        command = entry.get(self.distro) if os_name == "Linux" else None
        command = command or entry.get("command")
        if not command:
            return None
        return {
            "key": key,
            "os": os_name,
            "distro": self.distro if os_name == "Linux" else os_name.lower(),
            "command": command,
            "risk": entry.get("risk", "Low"),
            "explanation": entry.get("explanation", ""),
        }

    def list_actions(self) -> list[dict]:
        actions = []
        for key in sorted(self.command_catalog.get("actions", {})):
            item = self.get_action(key)
            if item:
                actions.append(item)
        return actions

    def translate_command(self, cmd: str, distro: str) -> str:
        # Check Adaptive Command Registry first
        try:
            from self_healing import command_registry
            from command_adaptation import detect_os_profile
            profile = detect_os_profile(self)
            resolved = command_registry.resolve_command(
                cmd, 
                self.os_name, 
                profile.get("version", "") or profile.get("os_version", ""), 
                profile.get("kernel", "")
            )
            if resolved != cmd:
                from logger import log_action
                log_action("SYNC", cmd, f"Adapted to: {resolved}", friendly_summary="Command Registry Synchronization applied.")
                return resolved
        except Exception:
            pass

        if distro == "debian" or distro == "windows" or self.os_name != "Linux":
            return cmd
        
        cmd_lower = cmd.lower()
        
        # 1. Python missing
        if "apt-get install" in cmd_lower and "python3 python3-pip" in cmd_lower:
            if distro == "fedora":
                return "sudo dnf install -y python3 python3-pip"
            elif distro == "arch":
                return "sudo pacman -S --noconfirm python python-pip"
                
        # 2. Node.js missing
        if "apt-get install" in cmd_lower and "nodejs npm" in cmd_lower:
            if distro == "fedora":
                return "sudo dnf install -y nodejs npm"
            elif distro == "arch":
                return "sudo pacman -S --noconfirm nodejs npm"
                
        # 3. Git missing
        if "apt-get install" in cmd_lower and " git" in cmd_lower:
            if distro == "fedora":
                return "sudo dnf install -y git"
            elif distro == "arch":
                return "sudo pacman -S --noconfirm git"
                
        # 4. Docker missing
        if "apt-get install" in cmd_lower and "docker.io" in cmd_lower:
            if distro == "fedora":
                return "sudo dnf install -y docker-ce docker-ce-cli containerd.io && sudo systemctl enable --now docker"
            elif distro == "arch":
                return "sudo pacman -S --noconfirm docker && sudo systemctl enable --now docker"
                
        # 5. Java missing
        if "apt-get install" in cmd_lower and "default-jdk" in cmd_lower:
            if distro == "fedora":
                return "sudo dnf install -y java-latest-openjdk-devel"
            elif distro == "arch":
                return "sudo pacman -S --noconfirm jdk-openjdk"
                
        # 6. Android Studio missing
        if "snap install android-studio" in cmd_lower:
            if distro == "fedora":
                return "sudo snap install android-studio --classic || flatpak install -y flathub com.google.AndroidStudio"
            elif distro == "arch":
                return "sudo pacman -S --noconfirm flatpak && flatpak install -y flathub com.google.AndroidStudio"
                
        # 7. install_nvidia_drivers
        if "ubuntu-drivers install" in cmd_lower:
            if distro == "fedora":
                return "sudo dnf install -y fedora-workstation-repositories && sudo dnf config-manager --set-enabled rpmfusion-nonfree-nvidia-driver && sudo dnf install -y akmod-nvidia xorg-x11-drv-nvidia-cuda"
            elif distro == "arch":
                return "sudo pacman -S --noconfirm nvidia nvidia-utils nvidia-settings"

        # 8. System Package Updates
        if ("apt-get update" in cmd_lower and "apt-get upgrade" in cmd_lower) or ("apt update" in cmd_lower and "apt upgrade" in cmd_lower):
            if distro == "fedora":
                return "sudo dnf upgrade -y"
            elif distro == "arch":
                return "sudo pacman -Syu --noconfirm"
            elif distro == "opensuse":
                return "sudo zypper refresh && sudo zypper update -y"

        # General package manager substitutions if possible
        if distro == "fedora":
            cmd = cmd.replace("apt-get install -y", "dnf install -y")
            cmd = cmd.replace("apt install -y", "dnf install -y")
        elif distro == "arch":
            cmd = cmd.replace("apt-get install -y", "pacman -S --noconfirm")
            cmd = cmd.replace("apt install -y", "pacman -S --noconfirm")
            
        return cmd

    def translate_command_for_os(self, cmd: str, recipe_os: str) -> str:
        if self.os_name == "Linux":
            return self.translate_command(cmd, self.distro)
        if self.os_name == "Darwin" and recipe_os == "Linux":
            return self._translate_linux_to_darwin(cmd)
        if self.os_name == "Windows" and recipe_os == "Linux":
            return self._translate_linux_to_windows(cmd)
        return cmd

    def _translate_linux_to_windows(self, cmd: str) -> str:
        import re
        cmd_lower = cmd.lower()
        # Clean up sudo prefix
        cmd = re.sub(r"\bsudo\b\s*", "", cmd).strip()
        cmd_lower = cmd.lower()
        
        replacements = [
            ("apt-get install -y python3 python3-pip", "winget install --id Python.Python.3 --exact --silent"),
            ("apt-get install -y git", "winget install --id Git.Git --exact --silent"),
            ("apt-get install -y nodejs npm", "winget install --id OpenJS.NodeJS --exact --silent"),
            ("apt-get install -y default-jdk", "winget install --id Oracle.JDK.21 --exact --silent"),
            ("snap install --classic code", "winget install --id Microsoft.VisualStudioCode --exact --silent"),
            ("snap install android-studio --classic", "winget install --id Google.AndroidStudio --exact --silent"),
            ("curl -sSL https://ollama.ai/install.sh | sudo bash", "powershell -NoProfile -ExecutionPolicy Bypass -Command \"iwr https://ollama.ai/install.ps1 -UseBasicParsing | iex\""),
            ("curl -sSL https://ollama.ai/install.sh | bash", "powershell -NoProfile -ExecutionPolicy Bypass -Command \"iwr https://ollama.ai/install.ps1 -UseBasicParsing | iex\""),
            ("apt-get install -y docker.io", "winget install --id Docker.DockerDesktop --exact --silent"),
            ("systemctl start docker", "Start-Service -Name com.docker.service"),
            ("systemctl enable docker", ""),
        ]
        for source, target in replacements:
            if source.lower() in cmd_lower:
                return target
        
        # Generic package install substitutions
        if "apt-get install -y" in cmd_lower or "apt install -y" in cmd_lower:
            parts = cmd.split()
            package = parts[-1] if parts else "package"
            package = package.replace("-y", "").strip()
            return f"winget install {package}"
            
        return cmd

    def _translate_linux_to_darwin(self, cmd: str) -> str:
        cmd_lower = cmd.lower()
        replacements = [
            ("sudo apt-get install -y python3 python3-pip", "brew install python"),
            ("sudo apt-get install -y git", "brew install git"),
            ("sudo apt-get install -y nodejs npm", "brew install node"),
            ("sudo apt-get install -y default-jdk", "brew install --cask temurin"),
            ("sudo snap install --classic code", "brew install --cask visual-studio-code"),
            ("sudo snap install android-studio --classic", "brew install --cask android-studio"),
            ("curl -sSL https://ollama.ai/install.sh | sudo bash", "curl -sSL https://ollama.ai/install.sh | bash"),
            ("sudo apt-get install -y docker.io && sudo systemctl enable --now docker", "brew install --cask docker"),
        ]
        for source, target in replacements:
            if source.lower() in cmd_lower:
                return target
        if "apt-get install" in cmd_lower:
            package = cmd.split()[-1] if cmd.split() else "package"
            return f"brew install {package}"
        return cmd

    def _check_internet(self) -> bool:
        try:
            with socket.create_connection(("8.8.8.8", 53), timeout=2):
                pass
            return True
        except Exception:
            return False

    # â”€â”€ DB helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _ensure_db(self):
        """Create tables if they don't exist yet."""
        with self._conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS recipes (
                    id          INTEGER PRIMARY KEY,
                    issue       TEXT    NOT NULL,
                    os          TEXT    NOT NULL,
                    command     TEXT    NOT NULL,
                    risk        TEXT    NOT NULL DEFAULT 'Low',
                    explanation TEXT    NOT NULL DEFAULT ''
                )"""
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS adaptive_knowledge_base (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    os_name TEXT NOT NULL,
                    os_version TEXT,
                    kernel_version TEXT,
                    error_pattern TEXT NOT NULL,
                    successful_fix TEXT NOT NULL,
                    default_fallback TEXT,
                    confidence_score REAL NOT NULL,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    verification_status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    last_verified TEXT NOT NULL,
                    fingerprint_id TEXT,
                    error_signature TEXT,
                    related_fixes TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learned_command_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_command TEXT NOT NULL,
                    failed_command TEXT NOT NULL,
                    replacement_command TEXT NOT NULL,
                    verification_result TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS self_healing_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    error_message TEXT NOT NULL,
                    error_source TEXT NOT NULL,
                    cause TEXT NOT NULL,
                    attempted_fix TEXT NOT NULL,
                    fix_source TEXT NOT NULL,
                    result TEXT NOT NULL,
                    safety_class TEXT NOT NULL,
                    validation_result TEXT NOT NULL,
                    archived INTEGER DEFAULT 0,
                    config_backup TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS error_intelligence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    error_signature TEXT NOT NULL,
                    error_raw TEXT NOT NULL,
                    command TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user',
                    os_snapshot TEXT,
                    candidates TEXT,
                    selected_fix TEXT,
                    outcome TEXT DEFAULT 'pending',
                    user_approved INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS shce_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    command TEXT NOT NULL,
                    error TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    candidates TEXT,
                    selected_candidate TEXT,
                    outcome_stdout TEXT,
                    outcome_stderr TEXT,
                    outcome_rc INTEGER
                )
            """)
            conn.commit()

    # â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def list_recipes(self, os_filter: Optional[str] = None) -> list[dict]:
        os_filter = os_filter or self.os_name
        db_os = os_filter
        if os_filter == "Darwin":
            db_os = "Linux"
        if self._check_internet():
            self.refresh_command_catalog()
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT id, issue, os, command, risk, explanation "
                "FROM recipes WHERE os=? ORDER BY issue",
                (db_os,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            for r in rows:
                r["os"] = os_filter
                r["command"] = self.translate_command_for_os(r["command"], db_os)
            existing_issues = {r["issue"].lower() for r in rows}
            for action_key, issue in ACTION_RECIPE_TITLES.items():
                if issue.lower() in existing_issues:
                    continue
                action = self.get_action(action_key, os_filter)
                if action:
                    rows.append({
                        "id": f"action:{action_key}",
                        "issue": issue,
                        "os": os_filter,
                        "command": action["command"],
                        "risk": action["risk"],
                        "explanation": action["explanation"],
                    })
                    existing_issues.add(issue.lower())
            if True:  # Always include system update recipe â€” it's locally generated from OS commands
                update_action = self.get_action("system_update", os_filter)
                if update_action:
                    rows.append({
                        "id": 999,
                        "issue": "System Package Updates",
                        "os": os_filter,
                        "command": update_action["command"],
                        "risk": update_action["risk"],
                        "explanation": update_action["explanation"],
                        "recipe_hint": "system_update",
                    })
            return rows

    def search_recipes(self, query: str) -> list[dict]:
        pattern = f"%{query}%"
        db_os = "Linux" if self.os_name == "Darwin" else self.os_name
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT id, issue, os, command, risk, explanation "
                "FROM recipes WHERE (issue LIKE ? OR explanation LIKE ?) AND os=?",
                (pattern, pattern, db_os),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            for r in rows:
                r["os"] = self.os_name
                r["command"] = self.translate_command_for_os(r["command"], db_os)
            if self._check_internet():
                update_action = self.get_action("system_update")
                if update_action:
                    update_recipe = {
                        "id": 999,
                        "issue": "System Package Updates",
                        "os": self.os_name,
                        "command": update_action["command"],
                        "risk": update_action["risk"],
                        "explanation": update_action["explanation"],
                        "recipe_hint": "system_update",
                    }
                    q_lower = query.lower()
                    if q_lower in update_recipe["issue"].lower() or q_lower in update_recipe["explanation"].lower():
                        rows.append(update_recipe)
            return rows

    def get_recipe(self, recipe_id: int) -> Optional[dict]:
        if recipe_id == 999 and self._check_internet():
            update_action = self.get_action("system_update")
            if not update_action:
                return None
            return {
                "id": 999,
                "issue": "System Package Updates",
                "os": self.os_name,
                "command": update_action["command"],
                "risk": update_action["risk"],
                "explanation": update_action["explanation"],
                "recipe_hint": "system_update",
            }
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT id, issue, os, command, risk, explanation FROM recipes WHERE id=?",
                (recipe_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            r = dict(zip(cols, row))
            if r["os"] == "Linux":
                r["command"] = self.translate_command(r["command"], self.distro)
            return r

    def run(self, command: str, trigger_shce: bool = True) -> tuple[str, str, int]:
        """Execute a shell command and return (stdout, stderr, returncode)."""
        import os
        import platform
        import re
        import shutil
        import tempfile

        exec_command = command
        is_windows = platform.system() == "Windows"
        
        # High timeout (30 minutes) to support large app downloads (Python, Android Studio, SDKs) without false timeouts
        timeout = 1800
        
        # Temp files for Windows elevation redirection
        temp_out_path = None
        temp_err_path = None

        current_os = platform.system()

        if current_os in ("Linux", "Darwin") and "sudo" in command.lower():
            if os.name == "posix" and os.geteuid() == 0:
                # Running as root inside Docker / container: remove sudo.
                exec_command = re.sub(r"\bsudo\b\s*", "", command)
            elif current_os == "Linux" and shutil.which("pkexec"):
                # Use pkexec for GUI privilege elevation on Linux desktops.
                cleaned = re.sub(r"\bsudo\b\s*", "", command)
                exec_command = ["pkexec", "bash", "-c", cleaned]
            # else: macOS (or Linux without pkexec) — pass sudo command through as-is;
            # the terminal/shell will prompt for the password in the normal way.
        elif is_windows and "sudo" in command.lower():
            # Strip sudo
            cleaned = re.sub(r"\bsudo\b\s*", "", command).strip()
            
            # Create temporary files to capture stdout/stderr from the elevated context
            fd_out, temp_out_path = tempfile.mkstemp(suffix=".txt", prefix="pcdoc_out_")
            fd_err, temp_err_path = tempfile.mkstemp(suffix=".txt", prefix="pcdoc_err_")
            os.close(fd_out)
            os.close(fd_err)
            
            # Reconstruct the command inside powershell to redirect output
            elevated_script = f"& {{ {cleaned} }} > '{temp_out_path}' 2> '{temp_err_path}'"
            elevated_script_escaped = elevated_script.replace("'", "''")
            
            # Formulate the powershell runas launcher
            exec_command = (
                f"powershell -NoProfile -ExecutionPolicy Bypass -Command "
                f"\"$p = Start-Process powershell -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', '{elevated_script_escaped}' "
                f"-Verb RunAs -Wait -PassThru -WindowStyle Hidden; exit $p.ExitCode\""
            )

        try:
            is_shell = isinstance(exec_command, str)
            proc = _safe_run(
                exec_command,
                shell=is_shell,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            stdout = proc.stdout
            stderr = proc.stderr
            rc = proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            timeout_msg = f"Command timed out after {timeout} seconds."
            stderr = f"{stderr}\n{timeout_msg}".strip()
            rc = 124

        # If we used temp files on Windows, read and clean them up
        if is_windows and temp_out_path and temp_err_path:
            try:
                if os.path.exists(temp_out_path):
                    with open(temp_out_path, "r", encoding="utf-8", errors="ignore") as f:
                        stdout = f.read()
                    os.remove(temp_out_path)
                if os.path.exists(temp_err_path):
                    with open(temp_err_path, "r", encoding="utf-8", errors="ignore") as f:
                        stderr = f.read()
                    os.remove(temp_err_path)
            except Exception as e:
                stderr = f"{stderr}\nError reading elevated output temp files: {e}".strip()

        # ──── SHCE Hook: trigger repair pipeline on command failure ──────────────
        if trigger_shce and rc != 0 and stderr:
            try:
                from shce_engine import shce as _shce
                _shce.handle_failure(
                    command=command,
                    error=(stderr or "").strip()[:2000],
                    source="repair_engine",
                    auto_queue=True,
                )
            except Exception:
                pass  # SHCE failure must never break the main execution path

        return stdout, stderr, rc

    def stream_run(self, command: str, trigger_shce: bool = True, timeout: int = 1800):
        """
        Execute a command and yield real-time output events as a generator:
        yield {"type": "log", "text": line, "stream": "stdout"|"stderr"}
        yield {"type": "progress", "percent": int, "detail": str}
        yield {"type": "done", "returncode": int, "stdout": full_stdout, "stderr": full_stderr, "ok": bool}
        """
        import os
        import platform
        import re
        import shutil
        import queue
        import threading
        import time

        exec_command = command
        is_windows = platform.system() == "Windows"
        current_os = platform.system()

        if current_os in ("Linux", "Darwin") and "sudo" in command.lower():
            if os.name == "posix" and os.geteuid() == 0:
                exec_command = re.sub(r"\bsudo\b\s*", "", command)
            elif current_os == "Linux" and shutil.which("pkexec"):
                cleaned = re.sub(r"\bsudo\b\s*", "", command)
                exec_command = ["pkexec", "bash", "-c", cleaned]
        elif is_windows and "sudo" in command.lower():
            cleaned = re.sub(r"\bsudo\b\s*", "", command).strip()
            exec_command = cleaned

        is_shell = isinstance(exec_command, str)

        try:
            proc = subprocess.Popen(
                exec_command,
                shell=is_shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1
            )
        except Exception as e:
            yield {"type": "log", "text": f"Process launch error: {e}", "stream": "stderr"}
            yield {"type": "done", "returncode": 1, "stdout": "", "stderr": str(e), "ok": False}
            return

        out_lines = []
        err_lines = []
        q = queue.Queue()

        def reader(pipe, stream_name):
            try:
                for line in iter(pipe.readline, ''):
                    if not line:
                        break
                    q.put((stream_name, line))
            except Exception:
                pass
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass

        t_out = threading.Thread(target=reader, args=(proc.stdout, "stdout"), daemon=True)
        t_err = threading.Thread(target=reader, args=(proc.stderr, "stderr"), daemon=True)
        t_out.start()
        t_err.start()

        start_time = time.time()
        last_progress = 0

        pct_regex = re.compile(r"(\b\d{1,3})%")
        mb_regex = re.compile(r"([\d\.]+)\s*(?:MB|GB|KB)\s*/\s*([\d\.]+)\s*(MB|GB|KB)", re.IGNORECASE)

        while True:
            if time.time() - start_time > timeout:
                try:
                    proc.kill()
                except Exception:
                    pass
                msg = f"\nCommand timed out after {timeout} seconds."
                err_lines.append(msg)
                yield {"type": "log", "text": msg, "stream": "stderr"}
                break

            try:
                stream_name, line = q.get(timeout=0.08)
                clean_line = line.rstrip("\r\n")
                if clean_line:
                    if stream_name == "stdout":
                        out_lines.append(clean_line)
                    else:
                        err_lines.append(clean_line)

                    yield {"type": "log", "text": clean_line, "stream": stream_name}

                    pct_match = pct_regex.search(clean_line)
                    if pct_match:
                        try:
                            val = int(pct_match.group(1))
                            if 0 <= val <= 100 and val != last_progress:
                                last_progress = val
                                yield {"type": "progress", "percent": val, "detail": clean_line[:120]}
                        except Exception:
                            pass
                    else:
                        mb_match = mb_regex.search(clean_line)
                        if mb_match:
                            try:
                                cur_val = float(mb_match.group(1))
                                total_val = float(mb_match.group(2))
                                if total_val > 0:
                                    calc_pct = min(100, max(0, int((cur_val / total_val) * 100)))
                                    if calc_pct != last_progress:
                                        last_progress = calc_pct
                                        yield {"type": "progress", "percent": calc_pct, "detail": clean_line[:120]}
                            except Exception:
                                pass

            except queue.Empty:
                if proc.poll() is not None:
                    while not q.empty():
                        try:
                            stream_name, line = q.get_nowait()
                            clean_line = line.rstrip("\r\n")
                            if clean_line:
                                if stream_name == "stdout":
                                    out_lines.append(clean_line)
                                else:
                                    err_lines.append(clean_line)
                                yield {"type": "log", "text": clean_line, "stream": stream_name}
                        except Exception:
                            break
                    break

        rc = proc.wait() if proc.poll() is not None else (124 if (time.time() - start_time > timeout) else proc.returncode)
        full_stdout = "\n".join(out_lines)
        full_stderr = "\n".join(err_lines)

        if trigger_shce and rc != 0 and full_stderr:
            try:
                from shce_engine import shce as _shce
                _shce.handle_failure(
                    command=command,
                    error=(full_stderr or "").strip()[:2000],
                    source="repair_engine",
                    auto_queue=True,
                )
            except Exception:
                pass

        yield {
            "type": "done",
            "returncode": rc,
            "stdout": full_stdout,
            "stderr": full_stderr,
            "ok": rc == 0
        }


# â”€â”€ RepairCommandManager â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class RepairCommandManager:
    """
    Manages command synchronization between the Repair Queue UI and the
    SHCE queue database.  Acts as the single source of truth for which
    command will actually be executed when a queued fix is approved.

    The SHCE queue table stores repair candidates in the ``shce_queue``
    table; the column ``selected_candidate`` holds the command that will
    run on approval.  Any edit made by the user in the Repair Queue UI
    must be persisted to that column so the display and the execution
    path stay in sync (Requirement 3.3).
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path

    # â”€â”€ internal helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # â”€â”€ public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def update_command(self, error_id: str, new_command: str) -> bool:
        """
        Persist *new_command* as the ``selected_candidate`` for the queue
        item identified by *error_id* (the integer primary key of the
        ``shce_queue`` row).

        Only pending items may be updated; items that have already been
        approved, executed, or rejected are immutable.

        Returns ``True`` when the update succeeded, ``False`` when the
        item was not found or is no longer pending.

        Raises ``ValueError`` when *new_command* is empty or whitespace.
        """
        new_command = (new_command or "").strip()
        if not new_command:
            raise ValueError("new_command must not be empty or whitespace")

        try:
            queue_id = int(error_id)
        except (TypeError, ValueError):
            raise ValueError(f"error_id must be a valid integer, got {error_id!r}")

        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE shce_queue
                SET    selected_candidate = ?
                WHERE  id = ? AND status = 'pending'
                """,
                (new_command, queue_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def get_display_command(self, error_id: str) -> Optional[str]:
        """
        Return the current ``selected_candidate`` command for the queue
        item identified by *error_id*, or ``None`` when the item does not
        exist.

        This is the single source of truth used by both the Repair Queue
        UI display and the approval execution path, ensuring that the
        command shown to the user is exactly the command that will run.
        """
        try:
            queue_id = int(error_id)
        except (TypeError, ValueError):
            raise ValueError(f"error_id must be a valid integer, got {error_id!r}")

        with self._conn() as conn:
            cur = conn.execute(
                "SELECT selected_candidate FROM shce_queue WHERE id = ?",
                (queue_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return row["selected_candidate"] or ""

