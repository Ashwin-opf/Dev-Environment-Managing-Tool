"""
Self-Healing Core Engine (SHCE)
================================
Intelligent command mutation, environment profiling, error intelligence,
and background repair queue. Integrates with the existing SafetyClassificationLayer
and CommandValidationSandbox from self_healing.py.

Safety Priority: Safety > Accuracy > Stability > Automation > Performance
"""
from __future__ import annotations

import asyncio
import datetime
import difflib
import json
import os
import platform
import re
import shutil
import socket
import sqlite3
import subprocess
import urllib.request
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# â”€â”€â”€ Path resolution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
BASE_DIR = Path(__file__).parent
try:
    from runtime_paths import get_runtime_db_path
    DB_PATH = os.getenv("DB_PATH", str(get_runtime_db_path()))
except Exception:
    DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "knowledge.db"))

# â”€â”€â”€ Cross-platform subprocess wrapper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Always decodes output as UTF-8 to prevent UnicodeDecodeError on Windows.
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

# â”€â”€â”€ Constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
MAX_CANDIDATES = 5
OLLAMA_TIMEOUT = 3.0
WEB_RAG_TIMEOUT = 4.0
CANDIDATE_SCORE_FLOOR = 0.1

# â”€â”€â”€ Extended error pattern library (40+ common Linux/Windows/macOS errors) â”€â”€â”€
_DOC_DB: List[Tuple[str, str, str, str]] = [
    # (os_match, pattern, fix, source_label)
    # â”€â”€ APT / dpkg â”€â”€
    ("Linux", r"dpkg.*lock|apt.*lock|unable to acquire.*lock",
     "sudo killall apt apt-get dpkg 2>/dev/null; sudo rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock; sudo dpkg --configure -a",
     "Debian APT Docs"),
    ("Linux", r"dpkg.*configure|half-configured|half-installed",
     "sudo dpkg --configure -a && sudo apt-get install -f -y",
     "Debian APT Docs"),
    ("Linux", r"unable to fetch|failed to fetch|404.*repository|no release file",
     "sudo apt-get update --fix-missing && sudo apt-get install -f -y",
     "Debian APT Docs"),
    ("Linux", r"unmet dependencies|broken packages|dependency.*problem",
     "sudo apt-get install -f -y && sudo dpkg --configure -a",
     "Debian APT Docs"),
    ("Linux", r"apt.*unreachable|could not connect|temporarily unavailable",
     "sudo systemctl restart NetworkManager && sleep 3 && sudo apt-get update",
     "Debian APT Docs"),
    # â”€â”€ Snap â”€â”€
    ("Linux", r"snap.*not found|snapd.*inactive|snap.*cannot be installed",
     "sudo systemctl enable --now snapd && sudo systemctl restart snapd",
     "Snap Documentation"),
    ("Linux", r"snap.*classic.*confinement|snap.*devmode",
     "sudo snap install {package} --classic",
     "Snap Documentation"),
    # â”€â”€ Flatpak â”€â”€
    ("Linux", r"flatpak.*remote.*not found|flatpak.*no remote",
     "flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo",
     "Flatpak Docs"),
    # â”€â”€ SystemD â”€â”€
    ("Linux", r"failed to start.*service|failed to restart.*service|unit.*not found",
     "sudo systemctl daemon-reload && sudo systemctl restart {service}",
     "systemd Documentation"),
    ("Linux", r"service.*masked|unit.*masked",
     "sudo systemctl unmask {service} && sudo systemctl start {service}",
     "systemd Documentation"),
    # â”€â”€ Docker â”€â”€
    ("Linux", r"docker.*daemon.*not running|cannot connect.*docker|docker.*refused",
     "sudo systemctl start docker && sudo systemctl enable docker",
     "Docker Documentation"),
    ("Linux", r"permission denied.*docker.sock",
     "sudo usermod -aG docker $USER && newgrp docker",
     "Docker Documentation"),
    ("Linux", r"docker.*no space left|docker.*disk space",
     "docker system prune -af --volumes",
     "Docker Documentation"),
    # â”€â”€ Python / pip â”€â”€
    ("*", r"pip.*externally.*managed|pip.*break.*system|PEP 668",
     "pip install --break-system-packages {package} || pip install --user {package}",
     "Python Packaging Docs"),
    ("*", r"pip.*no module named|modulenotfounderror",
     "pip install {package} --upgrade",
     "Python Packaging Docs"),
    ("*", r"pip.*ssl.*certificate|certificate verify failed",
     "pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org {package}",
     "Python Packaging Docs"),
    ("*", r"command.*pip.*not found|pip.*not installed",
     "python3 -m ensurepip --upgrade && python3 -m pip install --upgrade pip",
     "Python Packaging Docs"),
    # â”€â”€ npm / node â”€â”€
    ("*", r"npm.*eacces.*permission|npm.*permission denied",
     "mkdir -p ~/.npm-global && npm config set prefix '~/.npm-global' && export PATH=~/.npm-global/bin:$PATH",
     "npm Documentation"),
    ("*", r"npm.*network|npm.*registry|npm.*cannot fetch",
     "npm config set registry https://registry.npmjs.org/ && npm cache clean --force",
     "npm Documentation"),
    ("*", r"node.*command not found|nodejs.*not installed",
     "curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt-get install -y nodejs",
     "NodeSource Docs"),
    # â”€â”€ Git â”€â”€
    ("*", r"git.*ssl.*certificate|git.*unable to access.*ssl",
     "git config --global http.sslVerify false",
     "Git Documentation"),
    ("*", r"git.*not a repository|not a git repo",
     "git init",
     "Git Documentation"),
    # â”€â”€ NVIDIA / GPU drivers â”€â”€
    ("Linux", r"nvidia.*not found|nvidia.*driver.*missing|no nvidia.*detected",
     "sudo ubuntu-drivers autoinstall || sudo apt-get install -y nvidia-driver-535",
     "NVIDIA Linux Docs"),
    ("Linux", r"nouveau.*conflict|nouveau.*blacklist",
     "echo 'blacklist nouveau' | sudo tee /etc/modprobe.d/blacklist-nouveau.conf && sudo update-initramfs -u",
     "NVIDIA Linux Docs"),
    ("Linux", r"cuda.*not found|libcuda.*not found",
     "sudo apt-get install -y nvidia-cuda-toolkit",
     "NVIDIA CUDA Docs"),
    # â”€â”€ Network / DNS â”€â”€
    ("Linux", r"network.*unreachable|could not resolve host|dns.*resolution fail",
     "sudo systemctl restart NetworkManager && sudo systemctl restart systemd-resolved",
     "NetworkManager Docs"),
    ("Linux", r"address already in use|port.*already in use",
     "sudo fuser -k {port}/tcp",
     "Linux Networking Docs"),
    # â”€â”€ Disk / filesystem â”€â”€
    ("Linux", r"no space left on device|disk full|filesystem.*full",
     "du -sh /* 2>/dev/null | sort -rh | head -20",
     "Linux Disk Management"),
    ("Linux", r"read-only filesystem|filesystem.*read.only",
     "sudo mount -o remount,rw /",
     "Linux Disk Management"),
    # â”€â”€ Firewall â”€â”€
    ("Linux", r"ufw.*inactive|firewall.*not running",
     "sudo ufw enable",
     "UFW Documentation"),
    # â”€â”€ Ollama â”€â”€
    ("*", r"ollama.*not running|could not connect to ollama|ollama.*refused",
     "ollama serve &",
     "Ollama Documentation"),
    ("*", r"ollama.*model.*not found|ollama.*model.*pull",
     "ollama pull phi3:mini",
     "Ollama Documentation"),
    # â”€â”€ Windows â”€â”€
    ("Windows", r"winget.*not found|winget.*source.*error",
     "winget source reset --force",
     "Winget Documentation"),
    ("Windows", r"windows.*update.*error|wuauserv.*stopped",
     "powershell -Command \"Start-Service wuauserv; wuauclt /resetauthorization /detectnow\"",
     "Windows Update Docs"),
    ("Windows", r"wsl.*not installed|wsl.*command not found",
     "wsl --install",
     "WSL Documentation"),
    # â”€â”€ macOS â”€â”€
    ("Darwin", r"brew.*not found|homebrew.*not installed",
     "/bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"",
     "Homebrew Documentation"),
    ("Darwin", r"xcode.*select.*required|xcode.*command line tools",
     "xcode-select --install",
     "Xcode CLI Docs"),
    # â”€â”€ Generic permission â”€â”€
    ("*", r"permission denied|access denied|operation not permitted",
     "sudo {command}",
     "Linux Permissions Docs"),
    # â”€â”€ Environment variable â”€â”€
    ("*", r"command not found|not recognized as.*command|: not found",
     "which {command} || echo 'Tool not installed. Install with: sudo apt install {package}'",
     "Linux PATH Docs"),
]


# â”€â”€â”€ Environment Profiler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class EnvironmentProfiler:
    """Takes a real-time snapshot of the system environment."""

    @staticmethod
    def snapshot() -> Dict[str, Any]:
        os_name = platform.system()
        result: Dict[str, Any] = {
            "os_name": os_name,
            "os_label": EnvironmentProfiler._os_label(),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "hostname": socket.gethostname(),
            "package_manager": EnvironmentProfiler._detect_package_manager(os_name),
            "distro": EnvironmentProfiler._detect_distro(os_name),
            "network_online": EnvironmentProfiler._is_online(),
            "ollama_running": EnvironmentProfiler._check_ollama(),
            "gpu_info": EnvironmentProfiler._gpu_info(os_name),
            "memory_gb": EnvironmentProfiler._memory_gb(),
            "disk_free_gb": EnvironmentProfiler._disk_free_gb(),
            "cpu_count": os.cpu_count() or 0,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
        }
        return result

    @staticmethod
    def _os_label() -> str:
        os_name = platform.system()
        if os_name == "Linux":
            try:
                rel = platform.freedesktop_os_release()
                return (rel.get("PRETTY_NAME") or rel.get("NAME") or "Linux").split("(")[0].strip()
            except Exception:
                return "Linux"
        elif os_name == "Windows":
            return f"Windows {platform.release()}"
        elif os_name == "Darwin":
            return f"macOS {platform.mac_ver()[0]}"
        return os_name

    @staticmethod
    def _detect_distro(os_name: str) -> str:
        if os_name != "Linux":
            return os_name.lower()
        try:
            rel = platform.freedesktop_os_release()
            dist_id = (rel.get("ID") or "").lower()
            id_like = (rel.get("ID_LIKE") or "").lower()
            for kw in ("arch", "manjaro", "garuda"):
                if kw in dist_id or kw in id_like:
                    return "arch"
            for kw in ("fedora", "rhel", "centos", "nobara"):
                if kw in dist_id or kw in id_like:
                    return "fedora"
            for kw in ("opensuse", "suse"):
                if kw in dist_id or kw in id_like:
                    return "opensuse"
            for kw in ("debian", "ubuntu", "mint", "kali", "zorin"):
                if kw in dist_id or kw in id_like:
                    return "debian"
        except Exception:
            pass
        if shutil.which("pacman"):
            return "arch"
        if shutil.which("dnf"):
            return "fedora"
        if shutil.which("zypper"):
            return "opensuse"
        return "debian"

    @staticmethod
    def _detect_package_manager(os_name: str) -> str:
        if os_name == "Windows":
            return "winget"
        if os_name == "Darwin":
            return "homebrew"
        distro = EnvironmentProfiler._detect_distro(os_name)
        pm_map = {"debian": "apt", "fedora": "dnf", "arch": "pacman", "opensuse": "zypper"}
        return pm_map.get(distro, "apt")

    @staticmethod
    def _is_online() -> bool:
        try:
            with socket.create_connection(("8.8.8.8", 53), timeout=1.5):
                return True
        except Exception:
            return False

    @staticmethod
    def _check_ollama() -> bool:
        try:
            req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as r:
                return r.status == 200
        except Exception:
            return False

    @staticmethod
    def _gpu_info(os_name: str) -> str:
        try:
            if os_name == "Linux":
                result = _safe_run(
                    ["lspci", "-mm"],
                    capture_output=True, text=True, timeout=4
                )
                for line in result.stdout.splitlines():
                    if "VGA" in line or "3D controller" in line or "Display" in line:
                        parts = line.split('"')
                        if len(parts) >= 6:
                            return parts[5].strip()
                result2 = _safe_run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=3
                )
                if result2.returncode == 0 and result2.stdout.strip():
                    return result2.stdout.strip()
            elif os_name == "Windows":
                result = _safe_run(
                    ["powershell", "-Command",
                     "Get-WmiObject Win32_VideoController | Select-Object -ExpandProperty Name"],
                    capture_output=True, text=True, timeout=5
                )
                return result.stdout.strip().splitlines()[0] if result.stdout.strip() else "Unknown"
            elif os_name == "Darwin":
                result = _safe_run(
                    ["system_profiler", "SPDisplaysDataType"],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.splitlines():
                    if "Chipset Model" in line:
                        return line.split(":", 1)[-1].strip()
        except Exception:
            pass
        return "Unknown"

    @staticmethod
    def _memory_gb() -> float:
        try:
            import psutil
            return round(psutil.virtual_memory().total / (1024 ** 3), 1)
        except Exception:
            pass
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        return round(kb / (1024 ** 2), 1)
        except Exception:
            pass
        return 0.0

    @staticmethod
    def _disk_free_gb() -> float:
        try:
            usage = shutil.disk_usage("/")
            return round(usage.free / (1024 ** 3), 1)
        except Exception:
            return 0.0


# â”€â”€â”€ Error Intelligence DB â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class ErrorIntelligenceDB:
    """
    Manages the error_intelligence and shce_queue tables.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_tables()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        with self._conn() as conn:
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
        # Initialise the package knowledge store (idempotent)
        pks = PackageKnowledgeStore(self.db_path)
        pks.ensure_table()
        pks.seed()

    def log_error(self, command: str, error: str, candidates: List[Dict],
                  source: str = "user", os_snapshot: Optional[Dict] = None) -> int:
        sig = self._signature(error)
        with self._conn() as conn:
            cur = conn.execute("""
                INSERT INTO error_intelligence
                    (timestamp, error_signature, error_raw, command, source, os_snapshot, candidates, outcome)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """, (
                datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
                sig, error[:2000], command[:500], source,
                json.dumps(os_snapshot or {}),
                json.dumps(candidates)
            ))
            conn.commit()
            return cur.lastrowid or 0

    def update_outcome(self, error_id: int, outcome: str, selected_fix: str = "",
                       user_approved: bool = False) -> None:
        with self._conn() as conn:
            conn.execute("""
                UPDATE error_intelligence
                SET outcome = ?, selected_fix = ?, user_approved = ?
                WHERE id = ?
            """, (outcome, selected_fix, 1 if user_approved else 0, error_id))
            conn.commit()

    def enqueue(self, command: str, error: str, candidates: List[Dict],
                selected_candidate: Optional[str] = None) -> int:
        with self._conn() as conn:
            cur = conn.execute("""
                INSERT INTO shce_queue
                    (timestamp, command, error, status, candidates, selected_candidate)
                VALUES (?, ?, ?, 'pending', ?, ?)
            """, (
                datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
                command[:500], error[:2000],
                json.dumps(candidates),
                selected_candidate or ""
            ))
            conn.commit()
            return cur.lastrowid or 0

    def update_queue_item(self, queue_id: int, status: str,
                          stdout: str = "", stderr: str = "", rc: int = -1) -> None:
        with self._conn() as conn:
            conn.execute("""
                UPDATE shce_queue
                SET status = ?, outcome_stdout = ?, outcome_stderr = ?, outcome_rc = ?
                WHERE id = ?
            """, (status, stdout[:5000], stderr[:2000], rc, queue_id))
            conn.commit()

    def get_queue(self, status: Optional[str] = None, limit: int = 50) -> List[Dict]:
        with self._conn() as conn:
            if status:
                cur = conn.execute(
                    "SELECT * FROM shce_queue WHERE status = ? ORDER BY id DESC LIMIT ?",
                    (status, limit)
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM shce_queue ORDER BY id DESC LIMIT ?", (limit,)
                )
            return [dict(r) for r in cur.fetchall()]

    def get_error_log(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT * FROM error_intelligence ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset)
            )
            return [dict(r) for r in cur.fetchall()]

    def delete_error(self, error_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM error_intelligence WHERE id = ?", (error_id,))
            conn.commit()

    def delete_queue_item(self, queue_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM shce_queue WHERE id = ?", (queue_id,))
            conn.commit()

    def get_error_count(self) -> int:
        with self._conn() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM error_intelligence")
            return cur.fetchone()[0]

    def get_queue_item(self, queue_id: int) -> Optional[Dict]:
        with self._conn() as conn:
            cur = conn.execute("SELECT * FROM shce_queue WHERE id = ?", (queue_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def _signature(error: str) -> str:
        """Reduce an error string to a normalised signature token."""
        sig = re.sub(r"['\"/\\()\[\]{}]", " ", error.lower())
        sig = re.sub(r"\b\d+\b", "N", sig)
        sig = re.sub(r"\s+", " ", sig).strip()
        return sig[:200]


# â”€â”€â”€ Verification Result â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@dataclass
class VerificationResult:
    """
    Structured result returned by PackageVerifier.verify().

    Fields
    ------
    package             : normalised package name that was checked
    verified            : True when confidence >= 70
    confidence          : integer 0â€“100
    source              : pipeline stage that produced the result
                          ("apt-cache" | "package_knowledge_store" | "local_rag" |
                           "web_rag" | "fuzzy_match" | "none")
    verification_source : same as source â€” explicit field for API contract
    command             : install command (present when confidence >= 70)
    reason              : human-readable explanation (present when confidence < 70)
    suggestion          : closest fuzzy-match name (when 40 <= confidence < 70)
    """

    package: str
    verified: bool
    confidence: int
    source: str
    verification_source: str
    command: Optional[str] = None
    reason: Optional[str] = None
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict with all fields (None values included as None/null)."""
        return {
            "package": self.package,
            "verified": self.verified,
            "confidence": self.confidence,
            "source": self.source,
            "verification_source": self.verification_source,
            "command": self.command,
            "reason": self.reason,
            "suggestion": self.suggestion,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationResult":
        """Reconstruct a VerificationResult from a dict (e.g. after JSON deserialisation)."""
        return cls(
            package=data["package"],
            verified=data["verified"],
            confidence=data["confidence"],
            source=data["source"],
            verification_source=data["verification_source"],
            command=data.get("command"),
            reason=data.get("reason"),
            suggestion=data.get("suggestion"),
        )


# â”€â”€â”€ Intent Detector â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class IntentDetector:
    """Classifies user queries and extracts package names for installation requests."""

    TRIGGER_WORDS = frozenset(["install", "get", "add", "setup"])

    @staticmethod
    def classify(query: str) -> Tuple[bool, Optional[str]]:
        """
        Returns (is_installation_request, package_name_or_None).
        package_name is normalised to lowercase.
        If trigger word found but no package token follows, returns (True, None).
        """
        # Check for any trigger word as a whole word (case-insensitive),
        # excluding occurrences prefixed by "re" or "un" (e.g. reinstall, uninstall).
        trigger_pattern = re.compile(
            r"(?<![a-z])(?<!re)(?<!un)\b(install|get|add|setup)\b",
            re.IGNORECASE,
        )
        if not trigger_pattern.search(query):
            return (False, None)
        return (True, IntentDetector._extract_package(query))

    @staticmethod
    def _extract_package(query: str) -> Optional[str]:
        """
        Regex extraction: find trigger word followed by whitespace and a token.
        Returns the token lowercased, or None if no match.
        Uses whole-word matching to exclude 'reinstall', 'uninstall'.
        Pattern: r'\\b(install|get|add|setup)\\s+(\\S+)'
        """
        m = re.search(
            r"\b(?<!re)(?<!un)(install|get|add|setup)\s+(\S+)",
            query,
            re.IGNORECASE,
        )
        if m:
            return m.group(2).lower()
        return None


# â”€â”€â”€ Package Knowledge Store â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class PackageKnowledgeStore:
    """
    Thin SQLite DAO for the package_knowledge table in knowledge.db.
    Stores known packages, their install methods, verification status, and metadata.
    """

    _SEED_PACKAGES = [
        "git", "docker.io", "nodejs", "python3", "curl", "wget", "vim", "htop",
        "tmux", "build-essential", "net-tools", "ffmpeg", "vlc", "gimp",
        "libreoffice", "openssh-server", "ufw", "fail2ban", "nginx", "postgresql",
    ]

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_table(self) -> None:
        """Create the package_knowledge table if it does not already exist."""
        try:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS package_knowledge (
                        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                        package_name        TEXT    NOT NULL UNIQUE,
                        install_method      TEXT    NOT NULL DEFAULT 'apt',
                        repository_required TEXT,
                        verification_status TEXT    NOT NULL DEFAULT 'unknown',
                        last_verified       TEXT,
                        fallback_methods    TEXT
                    )
                """)
                conn.commit()
        except Exception as e:
            print(f"[PackageKnowledgeStore] ensure_table error: {e}")

    def seed(self) -> None:
        """Idempotently insert the 20 seed packages (INSERT OR IGNORE)."""
        now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
        try:
            with self._conn() as conn:
                for pkg in self._SEED_PACKAGES:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO package_knowledge
                            (package_name, install_method, verification_status, last_verified)
                        VALUES (?, 'apt', 'verified', ?)
                        """,
                        (pkg, now),
                    )
                conn.commit()
        except Exception as e:
            print(f"[PackageKnowledgeStore] seed error: {e}")

    def get(self, package_name: str) -> Optional[Dict]:
        """
        Case-insensitive exact lookup.
        Returns a dict or None if not found.
        """
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    "SELECT * FROM package_knowledge WHERE LOWER(package_name) = LOWER(?)",
                    (package_name,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        except Exception as e:
            print(f"[PackageKnowledgeStore] get error: {e}")
            return None

    def upsert(self, package_name: str, **fields) -> None:
        """
        INSERT OR REPLACE a package record.
        Always refreshes last_verified to the current UTC timestamp.
        Accepted keyword args: install_method, repository_required,
                               verification_status, fallback_methods.
        """
        now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
        install_method = fields.get("install_method", "apt")
        repository_required = fields.get("repository_required", None)
        verification_status = fields.get("verification_status", "unknown")
        fallback_methods = fields.get("fallback_methods", None)
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO package_knowledge
                        (package_name, install_method, repository_required,
                         verification_status, last_verified, fallback_methods)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        package_name,
                        install_method,
                        repository_required,
                        verification_status,
                        now,
                        fallback_methods,
                    ),
                )
                conn.commit()
        except Exception as e:
            print(f"[PackageKnowledgeStore] upsert error: {e}")

    def list_all(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Paginated SELECT ordered alphabetically by package_name."""
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    "SELECT * FROM package_knowledge ORDER BY package_name LIMIT ? OFFSET ?",
                    (limit, offset),
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            print(f"[PackageKnowledgeStore] list_all error: {e}")
            return []

    def count(self) -> int:
        """Return total number of rows in package_knowledge."""
        try:
            with self._conn() as conn:
                cur = conn.execute("SELECT COUNT(*) FROM package_knowledge")
                return cur.fetchone()[0]
        except Exception as e:
            print(f"[PackageKnowledgeStore] count error: {e}")
            return 0


# â”€â”€â”€ Package Verifier â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class PackageVerifier:
    """
    Verifies package existence through a 5-source pipeline before generating
    installation commands. Only packages with confidence >= 70 receive a command.

    Pipeline order (stop at first VERIFIED result):
      1. apt-cache show  â†’ confidence 100
      2. apt-cache search â†’ confidence 80
      3. Package Knowledge Store â†’ confidence 80
      4. Local RAG (VectorSearch) â†’ confidence 60
      5. Web RAG (DuckDuckGo, online only) â†’ confidence 60
      Fuzzy fallback â†’ confidence 40
      None found â†’ confidence 0 (UNVERIFIED)
    """

    CONFIDENCE_GATE = 70  # commands only generated at or above this score

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._pks = PackageKnowledgeStore(db_path)
        self._has_apt = shutil.which("apt-cache") is not None

    def verify(self, package_name: str, online: bool = True) -> VerificationResult:
        """Run the full 5-source pipeline and return a VerificationResult."""
        # Raise ValueError for empty/whitespace-only names
        if not package_name or not package_name.strip():
            raise ValueError("package_name must not be empty or whitespace")

        pkg = package_name.strip().lower()

        # Run pipeline in order, stop at first non-None result
        confidence: Optional[int] = None
        source = "none"

        # Source 1: apt-cache show (confidence 100)
        c = self._apt_cache_show(pkg)
        if c is not None:
            confidence, source = c, "apt-cache"

        # Source 2: apt-cache search (confidence 80)
        if confidence is None:
            c = self._apt_cache_search(pkg)
            if c is not None:
                confidence, source = c, "apt-cache"

        # Source 3: Package Knowledge Store (confidence 80)
        if confidence is None:
            c = self._query_pks(pkg)
            if c is not None:
                confidence, source = c, "package_knowledge_store"

        # Source 4: Local RAG (confidence 60)
        if confidence is None:
            c = self._query_local_rag(pkg)
            if c is not None:
                confidence, source = c, "local_rag"

        # Source 5: Web RAG (online only, confidence 60)
        if confidence is None and online:
            c = self._query_web_rag(pkg)
            if c is not None:
                confidence, source = c, "web_rag"

        # Source 6: Snap metadata (confidence 75)
        if confidence is None:
            c = self._query_snap(pkg)
            if c is not None:
                confidence, source = c, "snap"

        # Source 7: Flatpak/Flathub metadata (confidence 70)
        if confidence is None:
            c = self._query_flatpak(pkg)
            if c is not None:
                confidence, source = c, "flatpak"

        # Fuzzy fallback (confidence 40)
        fuzzy_score, fuzzy_suggestion = self._fuzzy_match(pkg)

        # Final confidence resolution
        if confidence is None:
            if fuzzy_score == 40:
                confidence = 40
                source = "fuzzy_match"
            else:
                confidence = 0
                source = "none"

        # Build result
        verified = confidence >= self.CONFIDENCE_GATE
        command: Optional[str] = None
        reason: Optional[str] = None
        suggestion: Optional[str] = None

        if verified:
            # Look up install method from PKS; fallback based on verification source
            pks_record = self._pks.get(pkg)
            install_method = pks_record.get("install_method", "apt") if pks_record else "apt"
            # Override install_method based on which source verified the package
            if source == "snap":
                install_method = "snap"
            elif source == "flatpak":
                install_method = "flatpak"
            repository_required = pks_record.get("repository_required") if pks_record else None

            # Handle offline + external_repo case
            if not online and install_method == "external_repo":
                verified = False
                confidence = 0
                reason = (
                    "Package requires an external repository that cannot be added while offline. "
                    "Connect to the internet to install this package."
                )
                # Write unknown to PKS
                self._pks.upsert(pkg, verification_status="unknown")
            else:
                command = self._build_command(pkg, install_method, repository_required)
                # Write verified to PKS
                self._pks.upsert(pkg, install_method=install_method, verification_status="verified")
        else:
            if confidence == 40 and fuzzy_suggestion:
                # Fuzzy match found but not verified
                reason = "Package could not be verified locally. No installation command generated."
                suggestion = fuzzy_suggestion
            elif not online and confidence == 0:
                reason = (
                    "Package could not be verified locally. "
                    "Internet access unavailable. No installation command generated."
                )
            else:
                reason = "Package could not be verified locally. No installation command generated."

            # Write unknown to PKS
            self._pks.upsert(pkg, verification_status="unknown")

        return VerificationResult(
            package=pkg,
            verified=verified,
            confidence=confidence,
            source=source,
            verification_source=source,
            command=command,
            reason=reason,
            suggestion=suggestion,
        )

    def _apt_cache_show(self, pkg: str) -> Optional[int]:
        """Check apt-cache show â€” returns 100 on exact match, None otherwise."""
        if not self._has_apt:
            return None
        try:
            result = _safe_run(
                ["apt-cache", "show", pkg],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return 100
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass
        return None

    def _apt_cache_search(self, pkg: str) -> Optional[int]:
        """Check apt-cache search --names-only â€” returns 80 on any result, None otherwise."""
        if not self._has_apt:
            return None
        try:
            result = _safe_run(
                ["apt-cache", "search", "--names-only", pkg],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return 80
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass
        return None

    def _query_pks(self, pkg: str) -> Optional[int]:
        """Query local Package Knowledge Store â€” returns 80 if verified record found."""
        record = self._pks.get(pkg)
        if record and record.get("verification_status") == "verified":
            return 80
        return None

    def _query_local_rag(self, pkg: str) -> Optional[int]:
        """Query local RAG (VectorSearch) â€” returns 60 on match, None otherwise."""
        try:
            from vector_search import VectorSearch
            vs = VectorSearch(self.db_path)
            results = vs.search(pkg, top_k=1)
            if results:
                return 60
        except Exception:
            pass
        return None

    def _query_web_rag(self, pkg: str) -> Optional[int]:
        """
        Query DuckDuckGo instant answer API for package information.
        Returns 60 on relevant result, None otherwise.
        NEVER called when online=False.
        """
        try:
            query = f"linux apt package {pkg} install"
            encoded = urllib.parse.quote_plus(query)
            url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
            req = urllib.request.Request(url, headers={"User-Agent": "PC-Doctor/1.0 SHCE-Verifier"})
            with urllib.request.urlopen(req, timeout=WEB_RAG_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            abstract = payload.get("Abstract", "") or ""
            answer = payload.get("Answer", "") or ""
            text = f"{abstract} {answer}".lower()
            # Check if the package name appears in the response
            if pkg.lower() in text and len(text) > 20:
                return 60
        except Exception:
            pass
        return None

    def _query_snap(self, pkg: str) -> Optional[int]:
        """Check if a package is available via Snap â€” returns 75 on match, None otherwise."""
        return None

    def _query_flatpak(self, pkg: str) -> Optional[int]:
        """Check if a package is available via Flatpak/Flathub â€” returns 70 on match, None otherwise."""
        if not shutil.which("flatpak"):
            return None
        try:
            result = _safe_run(
                ["flatpak", "search", pkg],
                capture_output=True, text=True, timeout=8
            )
            if result.returncode == 0 and result.stdout.strip() and pkg.lower() in result.stdout.lower():
                return 70
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass
        return None

    def _fuzzy_match(self, pkg: str) -> Tuple[int, Optional[str]]:
        """
        Compare pkg against all PKS package names using difflib.
        Returns (40, closest_name) if best ratio >= 0.7, else (0, None).
        """
        try:
            all_pkgs = [r["package_name"] for r in self._pks.list_all(limit=500)]
            if not all_pkgs:
                return (0, None)
            matches = difflib.get_close_matches(pkg, all_pkgs, n=1, cutoff=0.7)
            if matches:
                return (40, matches[0])
        except Exception:
            pass
        return (0, None)

    def _build_command(self, pkg: str, install_method: str, repository_required: Optional[str] = None) -> str:
        """Build the installation command based on the install method."""
        method = (install_method or "apt").lower()
        if method == "snap":
            return f"sudo snap install {pkg}"
        elif method == "flatpak" or install_method == "flatpak":
            return f"flatpak install -y flathub {pkg}"
        elif method == "external_repo" and repository_required:
            # Two-step: add repo then install
            return (
                f"sudo add-apt-repository -y {repository_required} && "
                f"sudo apt-get update && sudo apt-get install -y {pkg}"
            )
        elif method == "pip":
            return f"pip install {pkg}"
        elif method == "npm":
            return f"npm install -g {pkg}"
        else:
            # Default: apt
            return f"sudo apt install -y {pkg}"

    def heal_installation_failure(
        self, failed_package: str, online: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Self-healing: return ranked corrected candidates for a failed installation.
        Queries PKS, Local RAG, and optionally Web RAG for alternatives.
        """
        pkg = failed_package.strip().lower()
        candidates: List[Dict[str, Any]] = []

        # 1. Check PKS for alternative package names / install methods
        # Common alternatives map
        _ALTERNATIVES: Dict[str, List[str]] = {
            "docker": ["docker.io", "docker-ce"],
            "node": ["nodejs", "nodejs-lts"],
            "nodejs": ["nodejs"],
            "python": ["python3", "python3-full"],
            "vim": ["vim-gtk3", "vim-nox"],
            "java": ["default-jre", "default-jdk", "openjdk-17-jdk"],
            "pip": ["python3-pip"],
        }
        alts = _ALTERNATIVES.get(pkg, [])
        # Also check if PKS has any record with similar name
        pks_record = self._pks.get(pkg)
        if pks_record:
            fb_raw = pks_record.get("fallback_methods")
            if fb_raw:
                try:
                    fb_list = json.loads(fb_raw) if fb_raw.startswith("[") else [fb_raw]
                    alts = list(set(alts + fb_list))
                except Exception:
                    pass

        for alt_pkg in alts:
            alt_record = self._pks.get(alt_pkg)
            if alt_record and alt_record.get("verification_status") == "verified":
                install_method = alt_record.get("install_method", "apt")
                repo_req = alt_record.get("repository_required")
                cmd = self._build_command(alt_pkg, install_method, repo_req)
                candidates.append({
                    "command": cmd,
                    "package": alt_pkg,
                    "source": "package_knowledge_store",
                    "confidence": 80,
                    "rationale": f"Alternative package '{alt_pkg}' verified in local knowledge store",
                })

        # 2. Check PKS for repository_required to build two-step candidate
        if pks_record and pks_record.get("repository_required"):
            repo = pks_record["repository_required"]
            install_method = pks_record.get("install_method", "external_repo")
            cmd = self._build_command(pkg, install_method, repo)
            candidates.append({
                "command": cmd,
                "package": pkg,
                "source": "package_knowledge_store",
                "confidence": 70,
                "rationale": f"Repository '{repo}' required; two-step install generated",
            })

        # 3. Web RAG if online
        if online and not candidates:
            try:
                c = self._query_web_rag(pkg)
                if c:
                    candidates.append({
                        "command": f"sudo apt install -y {pkg}",
                        "package": pkg,
                        "source": "web_rag",
                        "confidence": 60,
                        "rationale": "Package found via web search; verify before executing",
                    })
            except Exception:
                pass

        # Sort by confidence descending
        candidates.sort(key=lambda c: -c.get("confidence", 0))
        return candidates


# â”€â”€â”€ Hybrid RAG Engine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class HybridRAGEngine:
    """
    Two-stage Hybrid Retrieval-Augmented Generation for error repair candidates.

    Stage 1 â€“ Sparse (BM25-style TF-IDF):
        Tokenises query and every document in the knowledge base + _DOC_DB.
        Scores by term-frequency Ã— inverse-document-frequency.  No external
        dependencies â€” pure stdlib.  Returns top-K semantically similar
        documents even when there is no exact substring match.

    Stage 2 â€“ Dense (Ollama embeddings):
        If Ollama is available, embeds the query and all candidate documents
        using the Ollama /api/embed endpoint and ranks by cosine similarity.
        Results are merged with Stage 1 scores (0.4 Ã— sparse + 0.6 Ã— dense).

    Stage 3 â€“ RAG-augmented generation:
        The retrieved context is prepended to the Ollama prompt so the model
        generates a fix grounded in proven solutions rather than hallucinating.
    """

    _STOP = frozenset({
        "the", "a", "an", "is", "in", "on", "at", "to", "of", "and", "or",
        "not", "no", "for", "with", "this", "that", "was", "are", "be",
        "by", "as", "it", "if", "so", "do", "get", "its",
    })

    def __init__(self, db_path: str = DB_PATH, os_name: Optional[str] = None):
        self.db_path = db_path
        self.os_name = os_name or platform.system()

    # â”€â”€ helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    @staticmethod
    def _tokenize(text: str) -> List[str]:
        tokens = re.findall(r"[a-zA-Z0-9_.-]+", text.lower())
        return [t for t in tokens if len(t) > 1 and t not in HybridRAGEngine._STOP]

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        return dot / (na * nb + 1e-9)

    # â”€â”€ Stage 1: sparse BM25-style retrieval â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def bm25_retrieve(
        self, query: str, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        BM25 retrieval over adaptive_knowledge_base + _DOC_DB pattern entries.
        Returns top_k (fix_command, source, score, rationale) dicts.
        """
        import math

        # Collect all documents: (error_text, fix_command, source, rationale)
        documents: List[Tuple[str, str, str, str]] = []

        # From adaptive_knowledge_base
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT error_pattern, successful_fix, source, confidence_score
                FROM adaptive_knowledge_base
                WHERE os_name = ? AND verification_status != 'Degraded'
                ORDER BY confidence_score DESC
                LIMIT 200
            """, (self.os_name,))
            for row in cur.fetchall():
                documents.append((
                    str(row[0]),
                    str(row[1]),
                    str(row[2]) if row[2] else "Knowledge Base",
                    f"KB entry (confidence {float(row[3]):.0%})"
                ))
            conn.close()
        except Exception:
            pass

        # From _DOC_DB pattern library
        for os_match, pattern, fix, source in _DOC_DB:
            if os_match != "*" and os_match != self.os_name:
                continue
            # Convert regex pattern to readable words for TF-IDF
            readable = re.sub(r"[\^\$\\\[\]().*+?|{}\\\/]", " ", pattern)
            documents.append((readable, fix, source, f"Doc pattern: {pattern[:60]}"))

        if not documents:
            return []

        # Build IDF
        query_tokens = set(self._tokenize(query))
        N = len(documents)
        doc_token_sets = [set(self._tokenize(doc[0])) for doc in documents]
        idf: Dict[str, float] = {}
        for token in query_tokens:
            df = sum(1 for s in doc_token_sets if token in s)
            idf[token] = math.log((N - df + 0.5) / (df + 0.5) + 1)

        # Score each document
        k1, b = 1.5, 0.75
        avg_dl = sum(len(s) for s in doc_token_sets) / max(N, 1)
        scored: List[Tuple[float, int]] = []
        for i, (doc_tokens_set) in enumerate(doc_token_sets):
            dl = len(doc_tokens_set)
            score = 0.0
            doc_tokens_list = self._tokenize(documents[i][0])
            for token in query_tokens:
                if token not in idf:
                    continue
                tf = doc_tokens_list.count(token)
                score += idf[token] * (tf * (k1 + 1)) / (
                    tf + k1 * (1 - b + b * dl / max(avg_dl, 1))
                )
            if score > 0:
                scored.append((score, i))

        scored.sort(key=lambda x: -x[0])
        results = []
        for score, idx in scored[:top_k]:
            _, fix_cmd, src, rationale = documents[idx]
            results.append({
                "command": fix_cmd,
                "source": f"Hybrid RAG Â· BM25 ({src})",
                "score": min(9.0, 5.0 + round(score, 1)),
                "rationale": f"Semantically similar: {rationale}",
                "_rag_score": score,
            })
        return results

    # â”€â”€ Stage 2: dense Ollama embedding retrieval â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _embed(self, text: str, model: str = "nomic-embed-text") -> Optional[List[float]]:
        """Call Ollama /api/embed and return the embedding vector."""
        try:
            data = json.dumps({"model": model, "input": text[:512]}).encode()
            req = urllib.request.Request(
                "http://localhost:11434/api/embed",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                payload = json.loads(resp.read().decode())
            # Ollama /api/embed returns {"embeddings": [[...]]}
            embeddings = payload.get("embeddings") or payload.get("embedding")
            if isinstance(embeddings, list) and embeddings:
                first = embeddings[0] if isinstance(embeddings[0], list) else embeddings
                return [float(x) for x in first]
        except Exception:
            pass
        return None

    def dense_retrieve(
        self, query: str, top_k: int = 3, embed_model: str = "nomic-embed-text"
    ) -> List[Dict[str, Any]]:
        """
        Dense retrieval using Ollama embeddings + cosine similarity.
        Falls back gracefully if Ollama is unavailable or embedding model missing.
        """
        query_vec = self._embed(query, embed_model)
        if query_vec is None:
            return []  # Ollama unavailable â€” skip

        # Embed all KB entries (limit for speed)
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT error_pattern, successful_fix, source, confidence_score
                FROM adaptive_knowledge_base
                WHERE os_name = ? AND verification_status != 'Degraded'
                ORDER BY confidence_score DESC LIMIT 80
            """, (self.os_name,))
            rows = cur.fetchall()
            conn.close()
        except Exception:
            return []

        scored: List[Tuple[float, str, str, str]] = []
        for error_pattern, fix, src, conf in rows:
            doc_vec = self._embed(str(error_pattern), embed_model)
            if doc_vec is None:
                continue
            sim = self._cosine(query_vec, doc_vec)
            if sim > 0.3:  # cosine threshold â€” ignore weak matches
                scored.append((sim, fix, src or "Knowledge Base", f"Dense similarity {sim:.2f}"))

        scored.sort(key=lambda x: -x[0])
        results = []
        for sim, fix_cmd, src, rationale in scored[:top_k]:
            results.append({
                "command": fix_cmd,
                "source": f"Hybrid RAG Â· Dense ({src})",
                "score": min(9.5, 5.0 + sim * 5),
                "rationale": f"Embedding similarity {sim:.2f}: {rationale}",
                "_rag_score": sim,
            })
        return results

    # â”€â”€ Stage 3: RAG-augmented Ollama generation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def rag_generate(
        self, error: str, context_items: List[Dict], os_name: str,
        distro: str = "debian", model: str = "phi3:mini"
    ) -> List[Dict[str, Any]]:
        """
        Prepend retrieved context to the Ollama prompt so the model generates
        a grounded fix rather than hallucinating from scratch.
        """
        if not context_items:
            return []

        context_lines = []
        for i, item in enumerate(context_items[:3], 1):
            context_lines.append(f"{i}. {item.get('command', '')}  # {item.get('source', '')}")
        context_block = "\n".join(context_lines)

        prompt = (
            f"You are a Linux system repair assistant.\n"
            f"OS: {os_name}, distro: {distro}.\n\n"
            f"Related known fixes from our knowledge base:\n{context_block}\n\n"
            f"New error to fix:\n{error[:400]}\n\n"
            f"Based on the known fixes above, suggest ONE shell command that will "
            f"most likely fix this error. Output ONLY the command, no explanation, "
            f"no markdown backticks."
        )
        try:
            data = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode())
            cmd = payload.get("response", "").strip()
            cmd = re.sub(r"^```[a-z]*\s*|```$", "", cmd, flags=re.MULTILINE).strip()
            if cmd and "\n" not in cmd and 3 < len(cmd) < 250:
                return [{
                    "command": cmd,
                    "source": f"Hybrid RAG Â· Ollama/{model} (grounded)",
                    "score": 6.5,
                    "rationale": "AI-generated fix grounded in retrieved similar solutions",
                }]
        except Exception:
            pass
        return []


def is_uninstall_command(command: str) -> bool:
    """Check if the command intent is to uninstall or remove software."""
    cmd_lower = command.lower().strip()
    keywords = ["remove", "purge", "uninstall", "delete", "rm -f", "rm -rf"]
    for kw in keywords:
        if kw in cmd_lower:
            return True
    return False


def _extract_uninstall_target(command: str) -> Optional[str]:
    """Extract target package or application name from an uninstall command."""
    parts = command.split()
    kw_idx = -1
    for i, part in enumerate(parts):
        p_low = part.lower()
        if p_low in ["remove", "purge", "uninstall", "delete"] or p_low.startswith("rm"):
            kw_idx = i
            break
            
    if kw_idx == -1:
        return None
        
    after = parts[kw_idx + 1:]
    targets = [p for p in after if not p.startswith("-")]
    if targets:
        return targets[0]
        
    return None


class CommandMutationEngine:
    """
    Generates and ranks up to MAX_CANDIDATES alternative commands for any failure.

    Candidate scoring (0â€“10 per factor):
        source_confidence  â€” Trusted KB=10, Experimental=8, Doc=7, Web=5, AI=3
        safety_score       â€” Safe=10, Caution=5, Dangerous=0, Blocked=-999
        distro_match       â€” exact=10, family=7, generic=5
        prior_success      â€” from adaptive_knowledge_base success_count / total
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.profiler = EnvironmentProfiler()
        self._env = self.profiler.snapshot()

    @property
    def os_name(self) -> str:
        return self._env.get("os_name") or platform.system()

    def _heal_uninstall_failure(self, target: str, command: str, error: str) -> List[Dict[str, Any]]:
        import shutil, subprocess
        from pathlib import Path
        import os
        
        target_lower = target.lower().strip()
        target_base = os.path.basename(target_lower)
        candidates = []
        
        FLATPAK_IDS = {
            "vs code": "com.visualstudio.code",
            "visual studio code": "com.visualstudio.code",
            "code": "com.visualstudio.code",
            "android studio": "com.google.AndroidStudio",
            "pycharm": "com.jetbrains.PyCharm-Community",
            "pycharm-community": "com.jetbrains.PyCharm-Community",
            "postman": "com.getpostman.Postman",
            "dbeaver ce": "io.dbeaver.DBeaverCommunity",
            "dbeaver-ce": "io.dbeaver.DBeaverCommunity",
            "slack": "com.slack.Slack",
            "brave": "com.brave.Browser",
            "chrome": "com.google.Chrome",
            "firefox": "org.mozilla.firefox",
            "sublime": "com.sublimetext.three",
            "sublime-text": "com.sublimetext.three",
        }

        SNAP_NAMES = {
            "vs code": "code",
            "visual studio code": "code",
            "pycharm": "pycharm-community",
            "pycharm-community": "pycharm-community",
            "android studio": "android-studio",
            "postman": "postman",
            "dbeaver ce": "dbeaver-ce",
            "dbeaver-ce": "dbeaver-ce",
            "slack": "slack",
            "sublime": "sublime-text",
            "sublime-text": "sublime-text",
            "firefox": "firefox",
        }

        APT_PKG_MAP = {
            "go": "golang-go",
            "golang": "golang-go",
            "golang-go": "golang-go",
            "node.js": "nodejs",
            "node": "nodejs",
            "python": "python3",
            "java": "default-jre default-jdk",
            "vs code": "code",
            "visual studio code": "code",
            "github cli": "gh",
            "gh": "gh",
            "neovim": "neovim",
            "android studio": "android-studio",
        }
        
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
            if not pkg or not pkg.strip():
                return False
            try:
                parts = pkg.split()
                if not parts:
                    return False
                r = _safe_run(
                    ["dpkg", "-l", parts[0]],
                    capture_output=True, text=True, timeout=3
                )
                return "ii " in r.stdout
            except Exception:
                return False

        # Build list of lookup keys
        lookup_keys = [k for k in [target_lower] if k and k.strip()]
        if target_base and target_base != target_lower:
            lookup_keys.append(target_base)
        for k in list(lookup_keys):
            if k and k.strip():
                lookup_keys.append(k.replace("-", " "))
                lookup_keys.append(k.replace(" ", "-"))
        lookup_keys = list(set(k.strip() for k in lookup_keys if k and k.strip()))
        
        flatpak_ids = []
        snap_names = []
        apt_pkgs = []
        
        for k in lookup_keys:
            if not k:
                continue
            f_id = FLATPAK_IDS.get(k)
            if f_id:
                flatpak_ids.append(f_id)
            elif "." in k:
                flatpak_ids.append(k)
                
            s_name = SNAP_NAMES.get(k)
            if s_name:
                snap_names.append(s_name)
            else:
                snap_names.append(k)
                
            a_pkg = APT_PKG_MAP.get(k)
            if a_pkg:
                apt_pkgs.append(a_pkg)
            else:
                apt_pkgs.append(k)
                
        flatpak_ids = list(set(flatpak_ids))
        snap_names = list(set(snap_names))
        apt_pkgs = list(set(apt_pkgs))
        
        # 1. Flatpak
        for fid in flatpak_ids:
            if _flatpak_installed(fid):
                candidates.append({
                    "command": f"flatpak uninstall -y {fid}",
                    "source": "SHCE Smart Uninstall",
                    "score": 9.5,
                    "rationale": f"Detected tool '{target}' is installed as Flatpak. Recommending flatpak uninstall."
                })
                
        # 2. Snap
        for sname in snap_names:
            if _snap_installed(sname):
                candidates.append({
                    "command": f"sudo snap remove --purge {sname}",
                    "source": "SHCE Smart Uninstall",
                    "score": 9.5,
                    "rationale": f"Detected tool '{target}' is installed as Snap. Recommending snap remove."
                })
                
        # 3. APT
        for apkg in apt_pkgs:
            if _apt_pkg_installed(apkg.split()[0]):
                candidates.append({
                    "command": f"sudo apt-get remove --purge -y {apkg} && sudo apt-get autoremove -y",
                    "source": "SHCE Smart Uninstall",
                    "score": 9.5,
                    "rationale": f"Detected tool '{target}' is installed via APT. Recommending apt-get remove."
                })
                
        # 4. PATH binary
        for k in lookup_keys:
            if shutil.which(k):
                bin_path = shutil.which(k)
                candidates.append({
                    "command": f"sudo rm -f {bin_path}",
                    "source": "SHCE Smart Uninstall",
                    "score": 9.0,
                    "rationale": f"Detected tool '{target}' exists as PATH binary at {bin_path}. Recommending manual removal."
                })
                
        # 5. Generic/Mapped fallbacks
        for k in lookup_keys:
            if k in ["go", "golang", "golang-go"]:
                candidates.append({
                    "command": "sudo apt-get remove --purge -y golang-go golang && sudo apt-get autoremove -y",
                    "source": "SHCE Smart Uninstall",
                    "score": 9.0,
                    "rationale": f"Mapped 'go' to standard APT package 'golang-go' for removal."
                })
            elif k in APT_PKG_MAP:
                mapped = APT_PKG_MAP[k]
                candidates.append({
                    "command": f"sudo apt-get remove --purge -y {mapped} && sudo apt-get autoremove -y",
                    "source": "SHCE Smart Uninstall",
                    "score": 8.0,
                    "rationale": f"Fallback: Suggest removing mapped APT package '{mapped}'."
                })
            elif k in SNAP_NAMES:
                mapped = SNAP_NAMES[k]
                candidates.append({
                    "command": f"sudo snap remove --purge {mapped}",
                    "source": "SHCE Smart Uninstall",
                    "score": 8.0,
                    "rationale": f"Fallback: Suggest removing mapped Snap package '{mapped}'."
                })
            elif k in FLATPAK_IDS:
                mapped = FLATPAK_IDS[k]
                candidates.append({
                    "command": f"flatpak uninstall -y {mapped}",
                    "source": "SHCE Smart Uninstall",
                    "score": 8.0,
                    "rationale": f"Fallback: Suggest removing mapped Flatpak package '{mapped}'."
                })
                
        # Deduplicate
        seen_cmds = set()
        unique_cands = []
        for c in candidates:
            c_norm = re.sub(r"\s+", " ", c["command"]).strip().lower()
            if c_norm not in seen_cmds:
                seen_cmds.add(c_norm)
                unique_cands.append(c)
                
        return unique_cands

    def generate_alternatives(
        self, command: str, error: str, max_results: int = MAX_CANDIDATES
    ) -> List[Dict[str, Any]]:
        """
        Main entry: returns list of ranked candidate dicts, each with:
            command, source, score, safety_class, rationale
        Only Safe and Caution candidates are returned (Blocked/Dangerous filtered out).
        """
        from self_healing import SafetyClassificationLayer, CommandValidationSandbox

        candidates: List[Dict[str, Any]] = []

        # Check if the command is a generic maintenance action name
        try:
            from repair_engine import RepairEngine
            engine = RepairEngine(Path(self.db_path))
            cleaned_cmd = command.strip().lower()
            generic_map = {
                "temp_cleanup": "temp_cleanup",
                "clear temp files": "temp_cleanup",
                "clear_temp_files": "temp_cleanup",
                "browser_cache_cleanup": "browser_cache_cleanup",
                "clean browser cache": "browser_cache_cleanup",
                "clean_browser_cache": "browser_cache_cleanup",
                "boost_ram": "boost_ram",
                "boost ram": "boost_ram",
                "flush ram cache": "boost_ram",
                "flush_ram_cache": "boost_ram",
                "startup_list": "startup_list",
                "manage startup programs": "startup_list",
                "manage_startup_programs": "startup_list",
                "system_update": "system_update",
                "update system packages": "system_update",
                "update_system_packages": "system_update",
                "remove_orphans": "remove_orphans",
                "remove orphan packages": "remove_orphans",
                "remove_orphan_packages": "remove_orphans",
            }
            
            action_key = generic_map.get(cleaned_cmd)
            if action_key:
                action_item = engine.get_action(action_key)
                if action_item and action_item.get("command"):
                    candidates.append({
                        "command": action_item["command"],
                        "source": "SHCE Adaptation Engine",
                        "score": 10.0,
                        "safety_class": "Safe",
                        "rationale": f"Mapped generic command '{command}' to OS-specific command: {action_item.get('explanation', '')}"
                    })
        except Exception:
            pass

        # 0a. Check for uninstall/remove failure
        if is_uninstall_command(command):
            target = _extract_uninstall_target(command)
            if target:
                uninstall_candidates = self._heal_uninstall_failure(target, command, error)
                if uninstall_candidates:
                    candidates.extend(uninstall_candidates)

        # 0. Check for tool installation or mapping request
        from command_adaptation import get_tool_install_command
        app_name = ""
        is_tool_install = False
        
        cmd_strip = command.strip().lower()
        if cmd_strip.startswith("install "):
            app_name = cmd_strip[8:]
            is_tool_install = True
        elif "not installed" in error.lower() or "command not found" in error.lower() or "not recognized" in error.lower():
            app_name = self._guess_package(command, error)
            is_tool_install = True
            
        if is_tool_install and app_name:
            inst_cmd, expl = get_tool_install_command(app_name)
            if inst_cmd:
                candidates.append({
                    "command": inst_cmd,
                    "source": "SHCE Adaptation Engine",
                    "score": 10.0,
                    "rationale": f"Automatically resolved installation command for '{app_name}': {expl}"
                })
                
        if cmd_strip.startswith("map "):
            action_key = cmd_strip[4:]
            if action_key == "driver_package_update":
                import platform
                if platform.system() == "Linux":
                    distro = self._env.get("distro", "debian")
                    if distro == "fedora":
                        drv_cmd = "sudo dnf upgrade -y linux-firmware kernel kernel-core kernel-modules"
                    elif distro == "arch":
                        drv_cmd = "sudo pacman -Syu --noconfirm linux-firmware linux"
                    else:
                        drv_cmd = "sudo apt-get update && sudo apt-get install --only-upgrade -y linux-firmware linux-generic linux-generic-hwe-24.04"
                elif platform.system() == "Windows":
                    drv_cmd = "winget upgrade --all --silent"
                else:
                    drv_cmd = "softwareupdate -ia"
                
                candidates.append({
                    "command": drv_cmd,
                    "source": "SHCE Adaptation Engine",
                    "score": 10.0,
                    "rationale": "Resolve missing driver update command for this system."
                })


        # 1. Local knowledge base (Trusted)
        candidates.extend(self._from_knowledge_base(error, "Trusted"))

        # 2. Local knowledge base (Experimental)
        if len(candidates) < max_results:
            candidates.extend(self._from_knowledge_base(error, "Experimental"))

        # 3. Pattern doc database
        # Skip doc-db for known generic maintenance action names to prevent cross-contamination.
        # e.g. a failed temp_cleanup on Windows may produce stderr that looks like a pip error,
        # which would wrongly suggest 'python3 -m ensurepip' as a fix.
        _KNOWN_GENERIC_ACTIONS = {
            "temp_cleanup", "clear temp files", "clear_temp_files",
            "browser_cache_cleanup", "clean browser cache", "clean_browser_cache",
            "boost_ram", "boost ram", "flush ram cache", "flush_ram_cache",
            "startup_list", "manage startup programs", "manage_startup_programs",
            "system_update", "update system packages", "update_system_packages",
            "remove_orphans", "remove orphan packages", "remove_orphan_packages",
            "driver_package_update", "driver_package_check",
        }
        if len(candidates) < max_results and command.strip().lower() not in _KNOWN_GENERIC_ACTIONS:
            candidates.extend(self._from_doc_db(error, command))

        # 3b. Generic "unable to locate" fix â€” ensure at least one candidate exists
        if len(candidates) < 1:
            pkg_match = re.search(r"unable to locate package\s+(\S+)", error, re.I)
            if not pkg_match:
                pkg_match = re.search(r"command not found[:\s]+(\S+)", error, re.I)
            if not pkg_match:
                pkg_match = re.search(r"(\S+):\s*command not found", error, re.I)
            if pkg_match:
                pkg_name = pkg_match.group(1).strip("'\"").lower()
                # Try alternative package names
                alt_map = {
                    "docker": ["docker.io", "docker-ce"],
                    "node": ["nodejs"],
                    "python": ["python3"],
                    "pip": ["python3-pip"],
                    "java": ["default-jre", "default-jdk"],
                }
                alts = alt_map.get(pkg_name, [pkg_name])
                for alt in alts[:2]:
                    candidates.append({
                        "command": f"sudo apt-get install -y {alt}",
                        "source": "SHCE Auto-Recovery",
                        "score": 6.0,
                        "rationale": f"Package '{pkg_name}' not found â€” trying '{alt}' as alternative",
                    })

        # 3c. Permission denied fix
        if "permission denied" in error.lower() and not command.strip().startswith("sudo"):
            candidates.append({
                "command": f"sudo {command.strip()}",
                "source": "SHCE Permission Fix",
                "score": 5.0,
                "rationale": "Retrying with sudo elevation for permission denied error",
            })

        # 4. Distro-aware mutation of the original command
        if len(candidates) < max_results:
            candidates.extend(self._distro_mutation(command))

        # 5. Package source expansion (snap, flatpak, pip)
        if len(candidates) < max_results:
            candidates.extend(self._package_source_expansion(command, error))

        # 5a. Hybrid RAG â€” Sparse BM25 retrieval (always on, no deps needed)
        rag_engine = HybridRAGEngine(self.db_path, os_name=self.os_name)
        bm25_hits = []
        if len(candidates) < max_results:
            bm25_hits = rag_engine.bm25_retrieve(error, top_k=3)
            # Only add BM25 results that aren't already covered by exact match
            existing_cmds = {re.sub(r"\s+", " ", c.get("command", "")).strip().lower() for c in candidates}
            for hit in bm25_hits:
                key = re.sub(r"\s+", " ", hit.get("command", "")).strip().lower()
                if key not in existing_cmds:
                    candidates.append(hit)

        # 5b. Hybrid RAG â€” Dense Ollama embedding retrieval (if Ollama available)
        dense_hits = []
        if len(candidates) < max_results and self._env.get("ollama_running"):
            dense_hits = rag_engine.dense_retrieve(error, top_k=2)
            existing_cmds = {re.sub(r"\s+", " ", c.get("command", "")).strip().lower() for c in candidates}
            for hit in dense_hits:
                key = re.sub(r"\s+", " ", hit.get("command", "")).strip().lower()
                if key not in existing_cmds:
                    candidates.append(hit)

        # 6. DuckDuckGo web RAG (if online)
        if len(candidates) < max_results and self._env.get("network_online"):
            candidates.extend(self._duckduckgo_rag(error))

        # 7. RAG-augmented Ollama generation (replaces plain Ollama fallback)
        if len(candidates) < max_results and self._env.get("ollama_running"):
            rag_context = (bm25_hits or []) + (dense_hits or [])
            rag_gen = rag_engine.rag_generate(
                error, rag_context,
                os_name=self.os_name,
                distro=self._env.get("distro", "debian"),
                model=os.getenv("SHCE_OLLAMA_MODEL", "phi3:mini")
            )
            candidates.extend(rag_gen)

        # 8. Plain Ollama AI fallback (last resort if RAG generate failed)
        if len(candidates) < max_results and self._env.get("ollama_running"):
            candidates.extend(self._ollama_fallback(error))

        # Deduplicate by normalised command
        seen: set[str] = set()
        unique: List[Dict] = []
        for c in candidates:
            key = re.sub(r"\s+", " ", c.get("command", "")).strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(c)

        # Safety classification + validation
        classified: List[Dict] = []
        for cand in unique:
            cmd = cand.get("command", "")
            safety_class = SafetyClassificationLayer.classify(cmd)

            # Hard filter: never surface Blocked commands
            if safety_class == "Blocked":
                continue
            # Soft filter: Dangerous commands get score penalty
            if safety_class == "Dangerous":
                cand["score"] = max(0, cand.get("score", 5) - 8)

            valid, reason = CommandValidationSandbox.validate(cmd)
            cand["safety_class"] = safety_class
            cand["validation"] = reason
            cand["executable_found"] = valid
            classified.append(cand)

        # Sort by score desc, then by safety (Safe first)
        order = {"Safe": 0, "Caution": 1, "Dangerous": 2}
        classified.sort(
            key=lambda c: (-c.get("score", 0), order.get(c.get("safety_class", "Safe"), 3))
        )
        return classified[:max_results]

    # â”€â”€ Source 1: Knowledge Base â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _from_knowledge_base(self, error: str, status: str) -> List[Dict]:
        results: List[Dict] = []
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("""
                SELECT successful_fix, source, confidence_score, success_count, failure_count
                FROM adaptive_knowledge_base
                WHERE os_name = ? AND verification_status = ?
                  AND ? LIKE '%' || error_pattern || '%'
                ORDER BY confidence_score DESC
                LIMIT 3
            """, (self.os_name, status, error))
            for row in cur.fetchall():
                fix, source, conf, sc, fc = row
                total = sc + fc
                prior = sc / total if total else conf
                score = 8 if status == "Trusted" else 6
                score = min(10, score + round(prior * 2, 1))
                results.append({
                    "command": fix,
                    "source": source or f"Knowledge Base ({status})",
                    "score": score,
                    "rationale": f"Previously successful fix ({status}, confidence {conf:.0%})",
                })
            conn.close()
        except Exception:
            pass
        return results

    # â”€â”€ Source 2: Pattern Doc Database â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _from_doc_db(self, error: str, original_cmd: str) -> List[Dict]:
        results: List[Dict] = []
        err_lower = error.lower()
        for os_match, pattern, fix, source in _DOC_DB:
            if os_match != "*" and os_match != self.os_name:
                continue
            if not re.search(pattern, err_lower):
                continue
            # Template substitution
            package = self._guess_package(original_cmd, error)
            service = self._guess_service(error)
            port = self._guess_port(error)
            resolved = (
                fix
                .replace("{package}", package)
                .replace("{command}", original_cmd.split()[0] if original_cmd else "command")
                .replace("{service}", service)
                .replace("{port}", port)
            )
            try:
                from app_context import engine
                resolved = engine.translate_command_for_os(resolved, "Linux")
            except Exception:
                pass
            results.append({
                "command": resolved,
                "source": source,
                "score": 7.0,
                "rationale": f"Matched documented error pattern: `{pattern}`",
            })
            if len(results) >= 2:
                break
        return results

    # â”€â”€ Source 3: Distro-aware mutation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _distro_mutation(self, command: str) -> List[Dict]:
        results: List[Dict] = []
        if self.os_name != "Linux":
            return results
        distro = self._env.get("distro", "debian")
        mutations: List[Tuple[str, str, str]] = [
            # (match, replacement, rationale)
            ("apt-get install -y", "dnf install -y", "fedora"),
            ("apt install -y", "dnf install -y", "fedora"),
            ("apt-get install -y", "pacman -S --noconfirm", "arch"),
            ("apt install -y", "pacman -S --noconfirm", "arch"),
            ("apt-get install -y", "zypper install -y", "opensuse"),
        ]
        cmd_lower = command.lower()
        for match, replacement, target_distro in mutations:
            if distro == target_distro and match in cmd_lower:
                mutated = command.replace(match, replacement)
                if mutated != command:
                    results.append({
                        "command": mutated,
                        "source": f"Distro Adaptation ({target_distro})",
                        "score": 6.5,
                        "rationale": f"Adapted command for {target_distro} package manager",
                    })
        return results

    # â”€â”€ Source 4: Package source expansion â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _package_source_expansion(self, command: str, error: str) -> List[Dict]:
        results: List[Dict] = []
        if self.os_name != "Linux":
            return results
        pkg = self._guess_package(command, error)
        if not pkg:
            return results
        # Try flatpak if installed
        if shutil.which("flatpak"):
            results.append({
                "command": f"flatpak install -y flathub {pkg}",
                "source": "Flatpak / Flathub",
                "score": 4.5,
                "rationale": f"Alternative installation via Flatpak",
            })
        return results

    # â”€â”€ Source 5: DuckDuckGo Instant Answer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _duckduckgo_rag(self, error: str) -> List[Dict]:
        results: List[Dict] = []
        try:
            query = f"linux fix: {error[:120]}"
            encoded = urllib.parse.quote_plus(query)
            url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
            req = urllib.request.Request(url, headers={"User-Agent": "PC-Doctor/1.0 SHCE"})
            with urllib.request.urlopen(req, timeout=WEB_RAG_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            # Extract commands from Abstract or RelatedTopics
            abstract = payload.get("Abstract", "")
            answer = payload.get("Answer", "")
            text = f"{abstract} {answer}"
            # Find code-like snippets (patterns starting with sudo / apt / dnf / pip etc.)
            cmd_patterns = re.findall(
                r"(?:sudo|apt|dnf|pacman|pip3?|npm|systemctl|docker|git|curl)\s[^\.\!\?<>\n]{5,80}",
                text
            )
            for cmd_snippet in cmd_patterns[:2]:
                cmd_snippet = cmd_snippet.strip()
                if cmd_snippet:
                    results.append({
                        "command": cmd_snippet,
                        "source": "DuckDuckGo Web Search",
                        "score": 4.0,
                        "rationale": "Extracted from DuckDuckGo Instant Answer",
                    })
        except Exception:
            pass
        return results

    # â”€â”€ Source 6: Ollama AI Fallback â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _ollama_fallback(self, error: str) -> List[Dict]:
        results: List[Dict] = []
        try:
            model = os.getenv("SHCE_OLLAMA_MODEL", "phi3:mini")
            prompt = (
                f"OS: {self.os_name}, distro: {self._env.get('distro', 'unknown')}.\n"
                f"Error: {error[:300]}\n"
                f"Reply with ONE shell command that fixes this. "
                f"Output ONLY the command, no explanation, no markdown."
            )
            req_data = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode())
            cmd = payload.get("response", "").strip()
            # Validate it looks like a command (single line, reasonable length)
            if cmd and "\n" not in cmd and 3 < len(cmd) < 200:
                # Strip any markdown fences that slipped through
                cmd = re.sub(r"^```[a-z]*\s*|```$", "", cmd).strip()
                results.append({
                    "command": cmd,
                    "source": f"Ollama AI ({model})",
                    "score": 3.0,
                    "rationale": "AI-generated fix suggestion (verify before executing)",
                })
        except Exception:
            pass
        return results

    # â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    @staticmethod
    def _guess_package(command: str, error: str) -> str:
        """Best-effort extraction of the package name from command/error."""
        for text in (command, error):
            # apt install X, pip install X, dnf install X etc.
            m = re.search(
                r"(?:install|add)\s+(?:-[ynqf\s]+\s+)?([a-zA-Z0-9._+-]+)(?:\s|$)",
                text
            )
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _guess_service(error: str) -> str:
        m = re.search(r"(?:service|unit)\s+([a-zA-Z0-9._-]+)", error.lower())
        return m.group(1) if m else "service"

    @staticmethod
    def _guess_port(error: str) -> str:
        m = re.search(r":(\d{2,5})\b", error)
        return m.group(1) if m else "8080"


# â”€â”€â”€ SHCE Orchestrator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class SHCEOrchestrator:
    """
    Main pipeline: detect_failure â†’ retrieve_context â†’ rank_candidates
                 â†’ validate â†’ queue_best â†’ store_outcome
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.mutation_engine = CommandMutationEngine(db_path)
        self.error_db = ErrorIntelligenceDB(db_path)
        self.profiler = EnvironmentProfiler()

    def handle_failure(
        self,
        command: str,
        error: str,
        source: str = "repair_engine",
        auto_queue: bool = True,
    ) -> Dict[str, Any]:
        """
        Full pipeline for a single failure event.
        Returns a summary dict with candidates, error_id, queue_id.
        """
        # â”€â”€ Installation-failure early branch â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Intercept "unable to locate package" errors before the generic path.
        _install_fail = re.search(r"unable to locate package\s+(\S+)", error, re.I)
        if _install_fail and not is_uninstall_command(command):
            return self._handle_installation_failure(command, error, source, auto_queue)

        env_snapshot = self.profiler.snapshot()
        candidates = self.mutation_engine.generate_alternatives(command, error)
        error_id = self.error_db.log_error(
            command=command,
            error=error,
            candidates=candidates,
            source=source,
            os_snapshot=env_snapshot,
        )

        best_candidate: Optional[str] = None
        queue_id: Optional[int] = None

        if candidates and auto_queue:
            # Auto-select best Safe candidate for the queue
            safe_candidates = [c for c in candidates if c.get("safety_class") == "Safe"]
            if safe_candidates:
                best_candidate = safe_candidates[0]["command"]
            else:
                best_candidate = candidates[0]["command"]

            queue_id = self.error_db.enqueue(
                command=command,
                error=error,
                candidates=candidates,
                selected_candidate=best_candidate,
            )
            try:
                self.error_db.update_outcome(error_id, 'queued', best_candidate)
            except Exception:
                pass
            
            # Synchronize with self_healing_attempts table
            try:
                from self_healing import self_healing_mgr
                best_cand_info = next((c for c in candidates if c["command"] == best_candidate), None)
                safety_class = best_cand_info.get("safety_class", "Safe") if best_cand_info else "Safe"
                val_res = best_cand_info.get("validation", "Passed") if best_cand_info else "Passed"
                
                self_healing_mgr.log_attempt(
                    error=error[:2000],
                    source=command[:500],
                    cause="SHCE automatically enqueued adaptation/error healing",
                    attempted_fix=best_candidate,
                    fix_source=best_cand_info.get("source", "SHCE Core") if best_cand_info else "SHCE Core",
                    result="Waiting User Approval",
                    safety_class=safety_class,
                    validation_result=val_res
                )
            except Exception:
                pass

        # NOTE: Do NOT call _auto_execute_and_register here.
        # Enqueued fixes should remain visible in the Repair Queue for user approval.
        # _auto_execute_and_register is only called after explicit user approval via /api/shce/approve.

        return {
            "error_id": error_id,
            "queue_id": queue_id,
            "candidates": candidates,
            "best_candidate": best_candidate,
            "environment": env_snapshot,
        }

    def _handle_installation_failure(
        self,
        command: str,
        error: str,
        source: str = "repair_engine",
        auto_queue: bool = True,
    ) -> Dict[str, Any]:
        """
        Handles 'unable to locate package X' errors via the PackageVerifier
        self-healing loop. Generates corrected candidates and enqueues the best.
        """
        match = re.search(r"unable to locate package\s+(\S+)", error, re.I)
        failed_pkg = match.group(1).strip().lower() if match else ""

        env_snapshot = self.profiler.snapshot()
        online = env_snapshot.get("network_online", False)

        verifier = PackageVerifier(self.db_path)
        candidates = verifier.heal_installation_failure(failed_pkg, online=online)

        if not candidates:
            # No alternatives found â€” update PKS and return failure
            PackageKnowledgeStore(self.db_path).upsert(
                failed_pkg, verification_status="unknown"
            )
            # Still log the error so it appears in Error Monitor
            error_id = self.error_db.log_error(
                command=command, error=error, candidates=[], source=source,
                os_snapshot=env_snapshot,
            )
            return {
                "ok": False,
                "error_id": error_id,
                "queue_id": None,
                "candidates": [],
                "best_candidate": None,
                "environment": env_snapshot,
                "message": (
                    f"Package '{failed_pkg}' cannot be installed through any verified method. "
                    f"No alternatives found in local knowledge store or online sources."
                ),
            }

        # Map heal candidates to the format expected by error_intelligence_db
        formatted = [
            {
                "command": c["command"],
                "source": c.get("source", "package_verifier"),
                "score": c.get("confidence", 60) / 10.0,  # normalise 0-100 â†’ 0-10
                "safety_class": "Safe",
                "rationale": c.get("rationale", ""),
            }
            for c in candidates
        ]

        error_id = self.error_db.log_error(
            command=command, error=error, candidates=formatted,
            source=source, os_snapshot=env_snapshot,
        )

        best_candidate: Optional[str] = None
        queue_id: Optional[int] = None

        if auto_queue:
            best_candidate = candidates[0]["command"]
            queue_id = self.error_db.enqueue(
                command=command,
                error=error,
                candidates=formatted,
                selected_candidate=best_candidate,
            )
            # NOTE: Do NOT auto-execute. Leave the fix in the Repair Queue for user approval.
            # User approves via /api/shce/approve/{queue_id}.

        return {
            "ok": True,
            "error_id": error_id,
            "queue_id": queue_id,
            "candidates": formatted,
            "best_candidate": best_candidate,
            "environment": env_snapshot,
            "message": (
                f"Found {len(candidates)} alternative(s) for '{failed_pkg}'. "
                f"Best candidate queued for approval."
            ),
        }

    def _auto_execute_and_register(self, queue_id: int, best_candidate: str, command: str, error_id: Optional[int] = None) -> None:
        """Runs enqueued candidate fix automatically as a test, updates history, database, and system scanner."""
        if queue_id is None or not best_candidate:
            return

        exec_res = self.execute_queued_fix(queue_id)
        if exec_res.get("ok"):
            if error_id:
                try:
                    self.error_db.update_outcome(error_id, 'resolved', best_candidate)
                except Exception:
                    pass
            # 1. Update recipes / catalog command replacement
            try:
                import sqlite3
                import json
                import datetime
                from pathlib import Path

                conn = sqlite3.connect(self.db_path)
                conn.execute("UPDATE recipes SET command = ? WHERE command = ?", (best_candidate, command))
                if "upgrade" in command or "update" in command:
                    conn.execute("UPDATE recipes SET command = ? WHERE issue = 'System Package Updates'", (best_candidate,))
                conn.commit()

                # Insert into learned_command_mappings so translation resolves it in the future
                conn.execute("""
                    INSERT INTO learned_command_mappings (original_command, failed_command, replacement_command, verification_result, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (command, command, best_candidate, "Success", datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")))
                conn.commit()
                conn.close()
            except Exception as e:
                print("[SHCE] Failed to update recipes/learned_command_mappings:", e)

            # Update catalog cache file
            try:
                catalog_path = Path(self.db_path).parent / "command_catalog_cache.json"
                if catalog_path.exists():
                    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
                    changed = False
                    if "actions" in catalog:
                        for action_key, action_entry in catalog["actions"].items():
                            for os_name, entry in action_entry.items():
                                if isinstance(entry, dict):
                                    for k, v in entry.items():
                                        if isinstance(v, str) and v == command:
                                            entry[k] = best_candidate
                                            changed = True
                                    if entry.get("command") == command:
                                        entry["command"] = best_candidate
                                        changed = True
                    if changed:
                        catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
            except Exception as e:
                print("[SHCE] Failed to update command_catalog_cache.json:", e)

            # 2. Mark the fix as completed in the scan
            try:
                from app_context import scanner
                cmd_lower = command.lower()
                type_mappings = {
                    "drop_caches": "memory",
                    "drop-caches": "memory",
                    "apt-get clean": "disk",
                    "rm -rf /tmp": "disk",
                    "apt-get check": "repository",
                    "sources.list": "repository",
                    "winget source": "repository",
                    "apt update": "updates",
                    "apt-get update": "updates",
                    "apt upgrade": "updates",
                    "apt-get upgrade": "updates",
                    "system_update": "updates",
                    "wuauserv": "service_wuauserv",
                    "restart": "service",
                    "start": "service",
                    "nvidia": "gpu_drivers",
                    "nouveau": "gpu_drivers",
                    "ubuntu-drivers": "gpu_drivers",
                    "python": "python_path",
                    "git": "git_path",
                    "docker": "docker_stopped",
                    "node": "node_path",
                    "npm": "npm_path"
                }

                types_to_remove = set()
                for key, itype in type_mappings.items():
                    if key in cmd_lower:
                        types_to_remove.add(itype)

                if hasattr(scanner, "latest_issues") and scanner.latest_issues:
                    new_issues = []
                    for issue in scanner.latest_issues:
                        itype = issue.get("type", "")
                        hint = issue.get("recipe_hint", "")
                        matched = False
                        if itype in types_to_remove:
                            matched = True
                        elif hint and hint.lower() in cmd_lower:
                            matched = True
                        elif "service_failed_" in itype and any(part in itype for part in cmd_lower.split()):
                            matched = True

                        if matched:
                            if not hasattr(scanner, "resolved_types"):
                                scanner.resolved_types = set()
                            scanner.resolved_types.add(itype)
                            if hint:
                                scanner.resolved_types.add(hint)
                        else:
                            new_issues.append(issue)
                    scanner.latest_issues = new_issues
            except Exception as e:
                print("[SHCE] Failed to mark scan completed:", e)

            # 3. Add to installed apps in Dev Tools if it is an app installation
            try:
                cmd_lower = command.lower()
                is_install = any(kw in cmd_lower for kw in ("install", "apt-get install", "apt install", "pip install", "npm install", "snap install", "winget install", "brew install"))
                if is_install:
                    known_tools = [
                        "git", "docker", "poetry", "pnpm", "pip", "npm", "python", "node", "code", "vscode",
                        "java", "snap", "android", "ollama", "rust", "go", "htop", "neovim", "gh", "fzf",
                        "jq", "tmux", "pycharm", "sublime", "postman", "dbeaver", "slack", "brave", "chrome", "firefox"
                    ]
                    matched_tool = None
                    for tool in known_tools:
                        import re
                        if re.search(r'\b' + re.escape(tool) + r'\b', cmd_lower):
                            matched_tool = tool
                            break
                    if not matched_tool:
                        parts = command.split()
                        if len(parts) > 1:
                            matched_tool = parts[-1]
                    if matched_tool:
                        from devtools_manager import devtools_manager
                        devtools_manager.install_tool({
                            "name": matched_tool.capitalize(),
                            "install_command": command,
                            "category": "Developer Tools",
                            "description": f"Installed automatically via self-healing pipeline."
                        })
            except Exception as e:
                print("[SHCE] Failed to add to installed apps:", e)
        else:
            if error_id:
                try:
                    self.error_db.update_outcome(error_id, 'failed', best_candidate)
                except Exception:
                    pass

    def execute_queued_fix(self, queue_id: int) -> Dict[str, Any]:
        """
        Execute the selected candidate from the SHCE queue.
        Requires prior user approval in the UI.
        Returns execution result dict.
        """
        from self_healing import SafetyClassificationLayer
        from repair_engine import RepairEngine
        from feature_flags import ENABLE_DEV_MODE

        item = self.error_db.get_queue_item(queue_id)
        if not item:
            return {"ok": False, "error": f"Queue item {queue_id} not found"}

        command = item.get("selected_candidate") or ""
        if not command:
            return {"ok": False, "error": "No command selected for this queue item"}

        # Final safety gate before execution
        safety_class = SafetyClassificationLayer.classify(command)
        if safety_class == "Blocked":
            self.error_db.update_queue_item(queue_id, "rejected", stderr="Blocked by safety layer", rc=-1)
            return {"ok": False, "error": "Command blocked by safety classifier"}

        # Execute
        self.error_db.update_queue_item(queue_id, "executing")
        
        # Execute via CentralizedExecutionEngine
        from execution_engine import execution_engine
        try:
            outcome = execution_engine.execute_command(
                command=command,
                operation="REPAIR",
                source="SHCE",
                trigger_shce=False,
            )
            stdout = outcome.stdout or ""
            stderr = outcome.stderr or outcome.message or ""
            rc = outcome.return_code if outcome.return_code is not None else (0 if outcome.success else -1)
        except Exception as exc:
            self.error_db.update_queue_item(queue_id, "failed", stderr=str(exc), rc=-1)
            return {"ok": False, "error": str(exc)}

        status = "executed" if rc == 0 else "failed"
        self.error_db.update_queue_item(queue_id, status, stdout=stdout, stderr=stderr, rc=rc)

        # Synchronize with self_healing_attempts table: update result to 'Healing Successful'
        if rc == 0:
            try:
                import sqlite3
                from self_healing import DB_PATH
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "UPDATE self_healing_attempts SET result = 'Healing Successful' "
                    "WHERE attempted_fix = ? OR attempted_fix = ? OR error_source = ?",
                    (command, item.get("command", ""), item.get("command", ""))
                )
                conn.commit()
                conn.close()
            except Exception as e:
                print("Failed to sync self_healing_attempts:", e)

        # Record knowledge
        if rc == 0:
            try:
                from self_healing import self_healing_mgr
                env = EnvironmentProfiler.snapshot()
                original_error = item.get("error", "")
                self_healing_mgr.record_knowledge(
                    os_name=env["os_name"],
                    os_version="",
                    kernel_version=env["kernel"],
                    error_pattern=ErrorIntelligenceDB._signature(original_error),
                    successful_fix=command,
                    default_fallback=item.get("command", ""),
                    source="SHCE Auto-Repair",
                    success=True,
                )
            except Exception:
                pass

        return {"ok": rc == 0, "stdout": stdout, "stderr": stderr, "returncode": rc, "status": status}

    def stream_execute_queued_fix(self, queue_id: int):
        """
        Execute the selected candidate from the SHCE queue and stream output events in real-time.
        Yields events: {"type": "log"|"progress"|"done", ...}
        """
        from self_healing import SafetyClassificationLayer
        from repair_engine import RepairEngine
        from feature_flags import ENABLE_DEV_MODE

        item = self.error_db.get_queue_item(queue_id)
        if not item:
            yield {"type": "log", "text": f"Queue item {queue_id} not found", "stream": "stderr"}
            yield {"type": "done", "ok": False, "error": f"Queue item {queue_id} not found", "returncode": -1}
            return

        command = item.get("selected_candidate") or ""
        if not command:
            yield {"type": "log", "text": "No command selected for this queue item", "stream": "stderr"}
            yield {"type": "done", "ok": False, "error": "No command selected", "returncode": -1}
            return

        safety_class = SafetyClassificationLayer.classify(command)
        if safety_class == "Blocked":
            self.error_db.update_queue_item(queue_id, "rejected", stderr="Blocked by safety layer", rc=-1)
            yield {"type": "log", "text": "Command blocked by safety layer", "stream": "stderr"}
            yield {"type": "done", "ok": False, "error": "Command blocked by safety layer", "returncode": -1}
            return

        self.error_db.update_queue_item(queue_id, "executing")
        yield {"type": "log", "text": f"Executing fix for repair #{queue_id}: {command}", "stream": "stdout"}

        from execution_engine import execution_engine
        full_stdout = ""
        full_stderr = ""
        rc = 0
        for event in execution_engine.stream_execute_command(command, operation="REPAIR", source="SHCE", trigger_shce=False):
            if event.get("type") == "done":
                full_stdout = event.get("stdout", "")
                full_stderr = event.get("stderr", "")
                rc = event.get("returncode", 0)
            yield event

        status = "executed" if rc == 0 else "failed"
        self.error_db.update_queue_item(queue_id, status, stdout=full_stdout, stderr=full_stderr, rc=rc)

        if rc == 0:
            try:
                import sqlite3
                from self_healing import DB_PATH
                conn = sqlite3.connect(DB_PATH)
                conn.execute(
                    "UPDATE self_healing_attempts SET result = 'Healing Successful' "
                    "WHERE attempted_fix = ? OR attempted_fix = ? OR error_source = ?",
                    (command, item.get("command", ""), item.get("command", ""))
                )
                conn.commit()
                conn.close()
            except Exception as e:
                print("Failed to sync self_healing_attempts:", e)

            try:
                from self_healing import self_healing_mgr
                env = EnvironmentProfiler.snapshot()
                original_error = item.get("error", "")
                self_healing_mgr.record_knowledge(
                    os_name=env["os_name"],
                    os_version="",
                    kernel_version=env["kernel"],
                    error_pattern=ErrorIntelligenceDB._signature(original_error),
                    successful_fix=command,
                    default_fallback=item.get("command", ""),
                    source="SHCE Auto-Repair",
                    success=True,
                )
            except Exception:
                pass

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Returns all data needed for the SHCE Control Center UI."""
        queue = self.error_db.get_queue(limit=20)
        error_log = self.error_db.get_error_log(limit=20)
        env = self.profiler.snapshot()

        # Knowledge base stats
        kb_stats = self._kb_stats()

        # Queue stats
        pending_count = sum(1 for q in queue if q.get("status") == "pending")
        executed_count = sum(1 for q in queue if q.get("status") == "executed")
        failed_count = sum(1 for q in queue if q.get("status") == "failed")
        total_queue = len(queue)

        # Auto-repair success rate
        success_rate = round(executed_count / max(total_queue, 1) * 100, 1)

        return {
            "ok": True,
            "status": {
                "core_active": True,
                "safety_ok": True,
                "ollama_running": env.get("ollama_running", False),
                "network_online": env.get("network_online", False),
                "auto_repairs_session": executed_count,
                "success_rate": success_rate,
                "queue_depth": pending_count,
            },
            "queue": queue,
            "error_log": error_log,
            "environment": env,
            "knowledge_base": kb_stats,
        }

    def _kb_stats(self) -> Dict[str, Any]:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM adaptive_knowledge_base")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM adaptive_knowledge_base WHERE verification_status='Trusted'")
            trusted = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM adaptive_knowledge_base WHERE verification_status='Experimental'")
            experimental = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM adaptive_knowledge_base WHERE verification_status='Degraded'")
            degraded = cur.fetchone()[0]
            cur.execute(
                "SELECT os_name, error_pattern, successful_fix, confidence_score, "
                "success_count, failure_count, verification_status, source, last_verified "
                "FROM adaptive_knowledge_base ORDER BY confidence_score DESC LIMIT 50"
            )
            entries = [dict(r) for r in cur.fetchall()]
            conn.close()
            return {
                "total": total, "trusted": trusted,
                "experimental": experimental, "degraded": degraded,
                "entries": entries,
            }
        except Exception:
            return {"total": 0, "trusted": 0, "experimental": 0, "degraded": 0, "entries": []}


# â”€â”€â”€ Module-level singletons â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
shce = SHCEOrchestrator(DB_PATH)
mutation_engine = CommandMutationEngine(DB_PATH)
error_intelligence_db = ErrorIntelligenceDB(DB_PATH)
env_profiler = EnvironmentProfiler()
package_knowledge_store = PackageKnowledgeStore(DB_PATH)

