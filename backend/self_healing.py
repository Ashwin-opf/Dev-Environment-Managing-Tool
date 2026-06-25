"""
Adaptive Self-Healing Engine – Classifies safety, validates sandbox,
resolves version-specific command overrides, and processes auto-remediations.
"""
import os
import re
import shutil
import sqlite3
import platform
import datetime
import urllib.request
import json
from pathlib import Path
from typing import Optional, Any, Tuple, Dict, List

BASE_DIR = Path(__file__).parent
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "knowledge.db"))

# Configuration
MAX_HEALING_ATTEMPTS = int(os.getenv("PC_DOCTOR_MAX_HEALING_ATTEMPTS", "3"))

# Classification rules regex patterns
BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/\s*(?:$|[\s;&|'\"])",
    r"rm\s+-rf\s+/\*",
    r"\b(mkfs|fdisk|parted|gparted|mkswap)\b",
    r"dd\s+if=.*of=/dev/",
    r":\(\)\{\s*:\|:\s*&\s*\}",
    r"shutdown\s+-[hPr]?\s*now",
    r"reboot",
    r"(\bof=|>>?)\s*/dev/(sd[a-z]|nvme[0-9]|mem|kmem|port)",
    r"del.*\bwindows[\\/]*system32",
    r"format\s+[Cc]:",
    r"reg\s+delete.*HKLM[\\/]*SYSTEM",
    r"\bmodprobe\b.*?(?:\s|^)(-(?:[a-zA-Z]*r|--remove))\b",
    r"\brmmod\b"
]

DANGEROUS_PATTERNS = [
    r"\b(kernel|kernel-core|kernel-modules|linux-image)\b",
    r"\b(grub|update-grub|bootloader|efi)\b",
    r"\b(sysctl)\b.*?(?:\s|^)(-(?:w|-write))\b",
    r"\bchown\s+-R\b",
    r"\bchmod\s+777\b",
    r"\bsudo\s+dd\b",
    r"\bnetsh\s+firewall\s+set\b",
    r"\b(apt-get|apt|dnf|pacman|zypper)\b.*\b(upgrade|dist-upgrade|full-upgrade|-Syu)\b"
]

CAUTION_PATTERNS = [
    r"\b(apt-get|apt|dnf|pacman|zypper|winget|brew)\b.*\b(install|update|remove|autoremove|clean)\b",
    r"\b(systemctl)\b.*\b(enable|disable|start|stop|restart|mask|unmask)\b",
    r"\b(ubuntu-drivers|akmod-nvidia|nvidia-settings|xorg-x11-drv-nvidia|linux-firmware)\b",
    r"\bsoftwareupdate\b",
    r"\bsetx\b",
    r"\breg\b"
]


class CommandValidationSandbox:
    @staticmethod
    def validate(command: str) -> Tuple[bool, str]:
        """
        Parses and validates syntax, executable existence, and permission requirements.
        Returns (passed: bool, reason: str).
        """
        cmd_stripped = command.strip()
        if not cmd_stripped:
            return False, "Command is empty."

        # Import safety methods to split tokens
        from safety import split_commands_and_args, extract_executable_and_args
        
        try:
            statements = split_commands_and_args(command)
        except Exception as e:
            return False, f"Syntax Error: Failed to parse shell statements. {e}"

        if not statements:
            return False, "No valid shell statements found."

        for stmt in statements:
            if not stmt:
                continue
            
            exe, args = extract_executable_and_args(stmt)
            if not exe:
                return False, "Empty statement / invalid environment variable prefix."
            
            # Check executable existence on PATH
            # Strip quotes or escaping from executable path if any
            exe_clean = exe.replace('"', '').replace("'", "").strip()
            
            # Allow common shell builtins
            SHELL_BUILTINS = {"echo", "cd", "set", "export", "exit", "sync", "del", "copy", "dir", "rm"}
            if exe_clean in SHELL_BUILTINS:
                continue

            if not shutil.which(exe_clean):
                # Check absolute path
                if not Path(exe_clean).exists():
                    return False, f"Validation Failed: Executable `{exe_clean}` not found on PATH."

            # Permission check: if command targets system configuration but lacks sudo/privileges
            if platform.system() == "Linux" and exe_clean in ("apt", "apt-get", "dnf", "pacman", "zypper", "systemctl"):
                is_root = os.geteuid() == 0 if hasattr(os, "geteuid") else False
                has_sudo = "sudo" in [t.lower() for t in stmt] or "pkexec" in [t.lower() for t in stmt]
                if not is_root and not has_sudo:
                    return False, f"Validation Failed: Admin tool `{exe_clean}` requires sudo or root privileges."

        return True, "Passed"


class SafetyClassificationLayer:
    @staticmethod
    def classify(command: str) -> str:
        """
        Classifies a command into: Blocked, Dangerous, Caution, Safe.
        """
        cmd_lower = command.lower()
        
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, cmd_lower):
                return "Blocked"
                
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, cmd_lower):
                return "Dangerous"
                
        for pattern in CAUTION_PATTERNS:
            if re.search(pattern, cmd_lower):
                return "Caution"
                
        return "Safe"


class AdaptiveCommandRegistry:
    def __init__(self):
        self.db_path = DB_PATH
        self._ensure_db()

    def _ensure_db(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
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
        conn.commit()
        conn.close()

    def resolve_command(self, cmd: str, os_name: str, os_version: str, kernel_version: str) -> str:
        """
        Resolves command mapping from registry in priority order:
        1. Exact OS + Version + Kernel match
        2. OS + Version match
        3. OS match
        4. Fallback command
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # We query and sort by version specificity
        cur.execute("""
            SELECT successful_fix, os_version, kernel_version, confidence_score, verification_status 
            FROM adaptive_knowledge_base 
            WHERE os_name = ? AND verification_status != 'Degraded' AND ? LIKE '%' || error_pattern || '%'
            ORDER BY 
              (CASE WHEN os_version = ? AND kernel_version = ? THEN 3
                    WHEN os_version = ? THEN 2
                    WHEN os_version IS NULL OR os_version = '' THEN 1
                    ELSE 0 END) DESC, confidence_score DESC
        """, (os_name, cmd, os_version, kernel_version, os_version))
        
        row = cur.fetchone()
        conn.close()
        
        if row:
            return row[0]
        return cmd


class SelfHealingManager:
    def __init__(self):
        self.db_path = DB_PATH
        self.registry = AdaptiveCommandRegistry()

    def log_attempt(self, error: str, source: str, cause: str, attempted_fix: str, fix_source: str, result: str, safety_class: str, validation_result: str, config_backup: Optional[str] = None):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO self_healing_attempts (
                error_message, error_source, cause, attempted_fix, fix_source, result, safety_class, validation_result, config_backup, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (error, source, cause, attempted_fix, fix_source, result, safety_class, validation_result, config_backup, datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")))
        conn.commit()
        conn.close()

    def record_knowledge(self, os_name: str, os_version: str, kernel_version: str, error_pattern: str, successful_fix: str, default_fallback: str, source: str, success: bool):
        """
        Saves or updates verified repairs in the adaptive knowledge base.
        Increments success/failure statistics, recalculates confidence score, and manages verification thresholds.
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # Check if knowledge already exists
        cur.execute("""
            SELECT id, success_count, failure_count, default_fallback 
            FROM adaptive_knowledge_base 
            WHERE os_name=? AND error_pattern=? AND successful_fix=?
        """, (os_name, error_pattern, successful_fix))
        row = cur.fetchone()
        
        now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
        
        if row:
            kid, sc, fc, fallback = row
            if success:
                sc += 1
            else:
                fc += 1
            
            # Confidence decay calculation
            total = sc + fc
            confidence = round(sc / total, 2)
            
            # Verification stages
            if total >= 5 and confidence >= 0.8:
                status = "Trusted"
            elif confidence < 0.4:
                status = "Degraded"
            else:
                status = "Experimental"
                
            cur.execute("""
                UPDATE adaptive_knowledge_base 
                SET success_count=?, failure_count=?, confidence_score=?, verification_status=?, last_verified=?
                WHERE id=?
            """, (sc, fc, confidence, status, now, kid))
        else:
            sc = 1 if success else 0
            fc = 0 if success else 1
            confidence = 1.0 if success else 0.0
            status = "Experimental"
            
            cur.execute("""
                INSERT INTO adaptive_knowledge_base (
                    os_name, os_version, kernel_version, error_pattern, successful_fix, default_fallback,
                    confidence_score, success_count, failure_count, verification_status, source, last_verified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (os_name, os_version, kernel_version, error_pattern, successful_fix, default_fallback, confidence, sc, fc, status, source, now))
            
        conn.commit()
        conn.close()

    def query_troubleshooting_sources(self, error: str, os_name: str, os_version: str, kernel_version: str) -> Tuple[Optional[str], str]:
        """
        Searches candidate solutions following the ranking priority:
        1. Local System Rules (predefined in sqlite/registry)
        2. Verified Knowledge Base (Trusted status)
        3. Official OS Documentation
        4. Official Package Manager Documentation
        5. Distribution Documentation
        6. Web Retrieval
        7. Ollama AI
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # 1. Search verified knowledge base (Trusted)
        cur.execute("""
            SELECT successful_fix, source FROM adaptive_knowledge_base 
            WHERE os_name=? AND verification_status='Trusted' AND ? LIKE '%' || error_pattern || '%'
            ORDER BY confidence_score DESC
        """, (os_name, error))
        row = cur.fetchone()
        if row:
            conn.close()
            return row[0], row[1]
            
        # 2. Search verified knowledge base (Experimental)
        cur.execute("""
            SELECT successful_fix, source FROM adaptive_knowledge_base 
            WHERE os_name=? AND verification_status='Experimental' AND ? LIKE '%' || error_pattern || '%'
            ORDER BY confidence_score DESC
        """, (os_name, error))
        row = cur.fetchone()
        if row:
            conn.close()
            return row[0], row[1]
            
        conn.close()

        # Helper to check internet connectivity
        online = self._is_online()

        # 3. Official OS / Package Manager / Distro Docs (Simulated / Local Fallback Rules)
        doc_fix = self._match_doc_database(error, os_name)
        if doc_fix:
            return doc_fix, "Official OS Documentation"

        # 4. Web Retrieval (if online)
        if online:
            web_fix = self._query_web_sources(error, os_name)
            if web_fix:
                return web_fix, "Web Retrieval"

        # 5. Ollama AI (if available, general fallback)
        ollama_fix = self._query_local_ollama(error, os_name)
        if ollama_fix:
            return ollama_fix, "Ollama AI"


        return None, "None"

    def _is_online(self) -> bool:
        import socket
        try:
            with socket.create_connection(("8.8.8.8", 53), timeout=1.5):
                return True
        except Exception:
            return False

    def _match_doc_database(self, error: str, os_name: str) -> Optional[str]:
        err_lower = error.lower()
        if os_name == "Linux":
            if "apt" in err_lower and ("lock" in err_lower or "unreachable" in err_lower):
                return "sudo killall apt apt-get dpkg; sudo rm -f /var/lib/dpkg/lock-frontend; sudo dpkg --configure -a"
            if "docker" in err_lower:
                return "sudo systemctl start docker"
            if "nouveau" in err_lower or "nvidia" in err_lower:
                return "sudo ubuntu-drivers install"
        elif os_name == "Windows":
            if "winget" in err_lower:
                return "winget source reset --force"
            if "wuauserv" in err_lower or "update" in err_lower:
                return "powershell -Command \"Start-Service wuauserv\""
        return None

    def _query_web_sources(self, error: str, os_name: str) -> Optional[str]:
        # Perform a simulated/mock web search query returning clean mappings
        # In a real environment, we'd query search APIs or scrapers
        err_lower = error.lower()
        if "lock" in err_lower:
            return "sudo rm -f /var/lib/dpkg/lock-frontend && sudo dpkg --configure -a"
        if "network" in err_lower or "mirror" in err_lower:
            return "sudo systemctl restart NetworkManager"
        return None

    def _query_local_ollama(self, error: str, os_name: str) -> Optional[str]:
        # Try to call local Ollama model
        try:
            req_data = {
                "model": "phi3:mini",
                "prompt": f"Recommend a single clean shell command to repair this error on {os_name}: '{error}'. Output ONLY the command, no explanations.",
                "stream": False
            }
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=json.dumps(req_data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=2.0) as res:
                payload = json.loads(res.read().decode("utf-8"))
                cmd = payload.get("response", "").strip()
                # Simple validation to verify Ollama output is a single command
                if cmd and "\n" not in cmd and len(cmd) < 150:
                    return cmd
        except Exception:
            pass
        return None

    # Snapshot and Rollback Operations
    def create_snapshot(self, paths: List[str]) -> str:
        """
        Creates a file-based snapshot for targets (e.g. config files)
        and returns a JSON string representing the backup.
        """
        backup_dict = {}
        for path_str in paths:
            path = Path(path_str)
            if path.exists() and path.is_file():
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    backup_dict[path_str] = content
                except Exception:
                    pass
        return json.dumps(backup_dict)

    def restore_snapshot(self, backup_json: str) -> bool:
        """
        Restores files from a JSON backup string.
        """
        if not backup_json:
            return False
        try:
            backup_dict = json.loads(backup_json)
            for path_str, content in backup_dict.items():
                path = Path(path_str)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            return True
        except Exception:
            return False


# Global Instantiations
self_healing_mgr = SelfHealingManager()
command_registry = AdaptiveCommandRegistry()
validation_sandbox = CommandValidationSandbox()
safety_classifier = SafetyClassificationLayer()
