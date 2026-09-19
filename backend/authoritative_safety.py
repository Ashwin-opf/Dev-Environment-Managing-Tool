"""
authoritative_safety.py — Authoritative Safety Layer & Live Pre-Execution Safety Gate.

Enforces:
- Hard safety blacklist and destructive pattern blocking.
- Host and internal PC Doctor resource protection rules.
- Closed blocked classification (Recoverable vs Non-recoverable).
- Explicit separation between execution tier (protection level) and safety authorization.
- Live Pre-Execution Safety Gate: Dynamic machine state check (disk space, RAM, locks, reboot, package managers)
  evaluated immediately before EVERY mutation, regardless of whether recipe is Static or Dynamic.
- Safety Evaluation Cache with granular invalidation.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


class BlockedReason(str, Enum):
    # Recoverable
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
    MISSING_RECIPE = "MISSING_RECIPE"
    OUTDATED_RECIPE = "OUTDATED_RECIPE"
    UNSUPPORTED_METHOD = "UNSUPPORTED_METHOD"
    MISSING_METADATA = "MISSING_METADATA"
    PACKAGE_MANAGER_UNAVAILABLE = "PACKAGE_MANAGER_UNAVAILABLE"
    RESOURCE_LOCKED = "RESOURCE_LOCKED"
    REQUIRES_REBOOT = "REQUIRES_REBOOT"
    PLATFORM_MISMATCH = "PLATFORM_MISMATCH"

    # Non-recoverable
    SAFETY_POLICY_REJECTED = "SAFETY_POLICY_REJECTED"
    DESTRUCTIVE_OPERATION = "DESTRUCTIVE_OPERATION"
    UNVERIFIABLE_DANGEROUS = "UNVERIFIABLE_DANGEROUS"
    RISK_ABOVE_HARD_LIMIT = "RISK_ABOVE_HARD_LIMIT"
    HOST_PROTECTION_VIOLATION = "HOST_PROTECTION_VIOLATION"
    INTERNAL_RESOURCE_PROTECTION = "INTERNAL_RESOURCE_PROTECTION"


@dataclass
class SafetyGateResult:
    allowed: bool
    blocked_reason: Optional[BlockedReason] = None
    is_recoverable: bool = False
    message: str = ""
    details: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "blocked_reason": self.blocked_reason.value if self.blocked_reason else None,
            "is_recoverable": self.is_recoverable,
            "message": self.message,
            "details": self.details or {},
        }


# Hard blacklist of destructive operations that are NEVER permitted
HARD_BLACKLIST = [
    r"rm\s+-rf\s+['\"]?/\s*(?:$|[\s;&|'\"])",                       # rm -rf /
    r"rm\s+-rf\s+['\"]?/\*['\"]?",                                  # rm -rf /*
    r"\b(mkfs|fdisk|parted|gparted|mkswap)\b",                 # disk partition formatting
    r"dd\s+if=.*of=/dev/(sd[a-z]|nvme[0-9]|mem|kmem|port)",    # raw disk wipe
    r":\(\)\{\s*:\|:\s*&\s*\}",                                # fork bomb
    r"shutdown\s+-[hPr]?\s*now",                               # sudden shutdown
    r"del\s+.*\\windows\\system32",                            # delete System32
    r"format\s+[A-Za-z]:",                                     # format drive
    r"reg\s+delete\s+.*HKLM\\SYSTEM",                          # delete registry SYSTEM
    r"\bmodprobe\b.*?(?:\s|^)(-(?:[a-zA-Z]*r|--remove))\b",   # unload kernel modules
    r"\brmmod\b",                                              # unload kernel modules
    # Stage 5 additions:
    r"\bbcdedit\b.*?(?:/delete|/deletevalue)\b",               # destructive boot alteration
    r"\bnet\s+user\s+.*?(?:/delete|/active:no)\b",              # destructive credential manipulation
    r"\b(userdel|deluser)\b.*?root\b",                         # destructive user deletion
    r"\bpasswd\b.*?(?:-d|--delete)\s+root\b",                  # root password wiping
    r"\bnetsh\s+advfirewall\s+set\s+allprofiles\s+state\s+off\b", # destructive firewall disabling
    r"\biptables\s+-F\b",                                      # flushing firewall rules without context
    r"(?:rmdir|rd)\s+.*?(?:/s|/q).*?(?:[A-Za-z]:\\|windows|system32)", # Windows root/system tree wiping
    r"del\s+.*?(?:/f|/s|/q).*?(?:windows\\system32|windows\\system|c:\\windows)", # Windows system wiping
    # Stage 9 additions: dangerous shell composition, chained destructive injection, download-and-execute
    r"(?:curl|wget|fetch|invoke-webrequest|iwr)\b.*?(?:\|\s*(?:sh|bash|zsh|dash|powershell|pwsh|cmd))\b", # untrusted remote execution pipe
    r"(?:\$\(|\`)\s*(?:curl|wget|iwr|rm\s+-rf|del\s+|format\s+)", # destructive command substitution
    r"(?:;|&&|\|\|)\s*(?:rm\s+-rf\s+['\"]?/\b|format\s+[A-Za-z]:|del\s+.*?(?:system32|windows)|drop\s+database\b)", # chained destructive commands
    r"\biex\b\s*\(?\s*(?:new-object\s+net\.webclient|iwr|curl|wget)", # PowerShell download string execution
    r"powershell.*?(?:iex|\-c|\-command).*?(?:downloadstring|webclient)", # PowerShell downloadstring execution
    r"\bchmod\s+.*?(?:777|666)\s+/",                           # dangerous root permissions opening
]

# Host protected patterns (OS kernel, firmware, low-level modules)
HOST_PROTECTED_PATTERNS = [
    r"\b(ubuntu-drivers|akmod-nvidia|nvidia-settings|xorg-x11-drv-nvidia|linux-firmware)\b",
    r"\b(kernel|kernel-core|kernel-modules|linux-generic|linux-generic-hwe|linux-image)\b",
]

# Minimum free disk space in GB required before running mutation operations
MIN_FREE_DISK_GB = 2.0


def is_natural_language_command(cmd: str) -> bool:
    """
    Detect if a string is human-readable/natural language advice rather than a real executable shell command.
    Guarantees that input like 'fix my git' or 'please install java' never spawns a shell process.
    """
    if not cmd or not isinstance(cmd, str):
        return False
    s = cmd.strip()
    if not s:
        return False

    # Obvious comment
    if s.startswith("#"):
        return True

    s_lower = s.lower()

    # Conversational imperative phrases
    nl_phrases = [
        "is installed",
        "are installed",
        "is currently active",
        "permission is required",
        "permission required",
        "administrator permission",
        "as administrator",
        "review path",
        "review configuration",
        "review python",
        "multiple versions",
        "multiple distinct",
        "missing from the system",
        "missing from path",
        "detected across system",
        "before changing it",
        "manual review required",
        "no automated command",
        "reinstall or restore",
        "inspect ",
        "unable to ",
        "failed to ",
        "please install",
        "please use",
        "cannot be upgraded",
        "add ",
        "by downloading",
        "download the",
        "downloading ",
        "installer ",
        "running it",
        "and running",
        "go to ",
        "navigate to ",
        "visit ",
        "refer to ",
        "you can ",
        "you should ",
        "you need to ",
        "make sure ",
        "ensure that ",
        "fix my ",
        "fix the ",
        "restart the ",
        "install java for me",
        "for me",
        "how do i ",
        "help me ",
    ]
    for phrase in nl_phrases:
        if phrase in s_lower:
            return True

    # Punctuation check
    has_sentence_period = s.endswith(".") and not any(s.endswith(ext) for ext in [".exe", ".bat", ".cmd", ".ps1", ".sh", ".py", ".js"])
    if has_sentence_period and len(s.split()) > 3:
        return True

    tokens = s.split()
    if not tokens:
        return False
    first_word = tokens[0].strip("\"'").rstrip(":,")
    first_word_lower = first_word.lower()

    # Known natural language conversational words
    nl_first_words = {
        "git", "mysql", "google", "multiple", "administrator", "review", 
        "python", "node", "docker", "java", "vscode", "please", "manual",
        "this", "the", "an", "a", "all", "warning", "error", "note", "info",
        "could", "would", "should", "how", "what", "why", "help"
    }
    if first_word_lower in nl_first_words:
        if len(tokens) >= 2:
            second_word = tokens[1].lower().rstrip(":,")
            if second_word in {
                "is", "server", "chrome", "versions", "permission", "path", 
                "precedence", "distinct", "installed", "detected", "required", 
                "install", "fix", "update", "run", "to", "do", "you"
            }:
                return True

    # Imperative English verbs followed by natural language pronouns/articles
    nl_imperative_verbs = {
        "fix", "repair", "install", "restart", "update", "check", "configure", 
        "download", "run", "setup", "clean", "remove", "reinstall", "resolve"
    }
    nl_pronouns_articles = {"my", "your", "the", "this", "that", "me", "for", "our", "all"}
    if first_word_lower in nl_imperative_verbs and len(tokens) >= 2:
        second_word = tokens[1].lower().rstrip(":,")
        if second_word in nl_pronouns_articles:
            return True

    return False


def check_package_manager_available(pm_name: str) -> bool:
    """Verifies that the requested package manager executable exists on the system."""
    if not pm_name or pm_name.lower() in ("native", "manual", "custom", "none", "unknown", "any", "system"):
        return True
    pm = pm_name.lower().strip()
    known_pms = {"winget", "choco", "scoop", "apt", "apt-get", "dnf", "yum", "pacman", "brew", "snap", "flatpak", "port", "zypper"}
    if pm in known_pms:
        return shutil.which(pm) is not None
    return True


@dataclass
class SafetyCacheEntry:
    result: SafetyGateResult
    timestamp: float
    command_hash: str
    machine_state_sig: str
    os_name: str


class SafetyEvaluationCache:
    """
    Thread-safe TTL cache for static pattern validations.
    Maintains machine-state sensitivity: last-mile dynamic checks (disk, locks, reboot)
    must always be validated against current host state.
    """
    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self.ttl = ttl_seconds
        self._cache: Dict[str, SafetyCacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, key: str, current_state_sig: str) -> Optional[SafetyGateResult]:
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            if time.time() - entry.timestamp > self.ttl:
                del self._cache[key]
                return None
            # If machine state signature changed, invalidate cache entry
            if entry.machine_state_sig != current_state_sig:
                del self._cache[key]
                return None
            return entry.result

    def set(self, key: str, result: SafetyGateResult, state_sig: str, os_name: str = "") -> None:
        with self._lock:
            self._cache[key] = SafetyCacheEntry(
                result=result,
                timestamp=time.time(),
                command_hash=key,
                machine_state_sig=state_sig,
                os_name=os_name,
            )

    def invalidate(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is not None:
                self._cache.pop(key, None)
            else:
                self._cache.clear()

    def clear(self) -> None:
        self.invalidate()


class AuthoritativeSafetyLayer:
    """Authoritative safety validator and dynamic live pre-execution gate."""

    def __init__(self) -> None:
        self._blacklist = [re.compile(p, re.IGNORECASE) for p in HARD_BLACKLIST]
        self._host_protected = [re.compile(p, re.IGNORECASE) for p in HOST_PROTECTED_PATTERNS]
        self.cache = SafetyEvaluationCache(ttl_seconds=30.0)

    def is_protected_pc_doctor_resource(self, command: str, target_path: Optional[str] = None) -> bool:
        """Protects PC Doctor internal source code, databases, and configuration from repair mutation."""
        cmd_lower = command.lower()
        destructive_verbs = ("del ", "rm ", "rmdir ", "rd ", "remove-item ", "erase ", "truncate ")
        has_destructive_verb = any(v in cmd_lower for v in destructive_verbs) or cmd_lower.startswith(("del", "rm", "rd", "rmdir"))

        protected_patterns = [
            r"\bknowledge.*\.db\b",
            r"\bauthoritative_safety\.py\b",
            r"\bexecution_engine\.py\b",
            r"\bexecution_tier\.py\b",
            r"\bprivilege_manager\.py\b",
            r"\bstate_refresh\.py\b",
            r"\brecipe_engine\.py\b",
            r"\bbackend(?=[\\/\s\"']|$)",
            r"\bfrontend(?=[\\/\s\"']|$)",
            r"\bpc-doc(?=[\\/\s\"']|$)",
        ]

        if has_destructive_verb:
            for p in protected_patterns:
                if re.search(p, cmd_lower):
                    return True

        if target_path:
            p_lower = str(target_path).lower()
            for p in protected_patterns:
                if re.search(p, p_lower):
                    return True

        return False

    def evaluate_command_static(self, command: str) -> Tuple[bool, Optional[BlockedReason], str]:
        """Static pattern check on command string."""
        cmd = command.strip()
        if not cmd:
            return False, BlockedReason.SAFETY_POLICY_REJECTED, "Empty command string is not allowed."

        if is_natural_language_command(cmd):
            return False, BlockedReason.SAFETY_POLICY_REJECTED, "Natural language guidance or advisory text detected; not an executable command."

        if self.is_protected_pc_doctor_resource(cmd):
            return False, BlockedReason.INTERNAL_RESOURCE_PROTECTION, "Command attempts to mutate protected PC Doctor internal code or database."

        for pattern in self._blacklist:
            if pattern.search(cmd):
                return False, BlockedReason.DESTRUCTIVE_OPERATION, f"Command contains blacklisted destructive pattern: {pattern.pattern}"

        for pattern in self._host_protected:
            if pattern.search(cmd):
                try:
                    from safety import _running_in_container
                    if _running_in_container() or os.getenv("PC_DOCTOR_ALLOW_HOST_SYSTEM_CHANGES", "").lower() in {"1", "true", "yes"}:
                        continue
                except Exception:
                    pass
                return False, BlockedReason.HOST_PROTECTION_VIOLATION, "Command attempts to alter host protected kernel or firmware modules."

        return True, None, "Command passed static pattern validation."

    def _extract_pm(self, command: str, package_manager: Optional[str] = None) -> Optional[str]:
        """Infers the package manager invoked by the command or explicit metadata."""
        if package_manager and package_manager.lower() not in ("native", "manual", "custom", "none", "unknown", "any", "system"):
            return package_manager.lower().strip()
        cmd_lower = command.strip().lower()
        for pm in ("winget", "choco", "scoop", "apt", "apt-get", "dnf", "yum", "pacman", "brew", "snap", "flatpak", "port", "zypper"):
            if cmd_lower.startswith(pm + " ") or f" {pm} " in cmd_lower or f"sudo {pm} " in cmd_lower:
                return pm
        return None

    def live_pre_execution_gate(
        self,
        command: str,
        operation: str = "MUTATION",
        required_disk_gb: float = MIN_FREE_DISK_GB,
        target_path: Optional[str] = None,
        is_static_recipe: bool = False,
        recipe: Optional[Any] = None,
        machine_state: Optional[Any] = None,
        package_manager: Optional[str] = None,
        target_resource: Optional[str] = None,
        owner_id: Optional[str] = None,
        allow_cached: bool = True,
    ) -> SafetyGateResult:
        """
        The authoritative Live Pre-Execution Safety Gate.
        Must run immediately before EACH mutation as the final authorization step.

        CRITICAL ARCHITECTURAL INVARIANT:
        Tier selection (e.g. Tier 3 Full Protected) specifies required protection and approval,
        NOT authorization to execute!
        A hard override to Tier 3 MUST NEVER bypass this live safety gate.
        """
        cmd_stripped = command.strip()

        # Build machine state signature for cache sensitivity
        state_sig = "none"
        if machine_state is not None:
            state_sig = (
                f"reboot:{getattr(machine_state, 'pending_reboot', None)}|"
                f"disk:{getattr(machine_state, 'free_disk_gb', None)}|"
                f"lock:{getattr(machine_state, 'dependency_lock', None)}|"
                f"pm_avail:{getattr(machine_state, 'package_manager_available', None)}"
            )

        # Check safety cache
        cache_key = f"{cmd_stripped}|static:{is_static_recipe}|op:{operation}"
        if allow_cached:
            cached = self.cache.get(cache_key, current_state_sig=state_sig)
            if cached is not None and not cached.allowed:
                # Always honor cached blocks immediately
                return cached

        # 1. Static pattern and natural language check
        passed, reason, msg = self.evaluate_command_static(cmd_stripped)
        if not passed:
            res = SafetyGateResult(
                allowed=False,
                blocked_reason=reason,
                is_recoverable=False,
                message=msg,
                details={"command": cmd_stripped},
            )
            self.cache.set(cache_key, res, state_sig, platform.system())
            return res

        # 2. Recipe & OS Platform mismatch check
        cur_os = platform.system()
        if recipe is not None and getattr(recipe, "os", None):
            rec_os = str(recipe.os).strip().lower()
            if rec_os not in ("any", "unknown", ""):
                cur_norm = cur_os.lower()
                # Normalize OS strings
                if rec_os in ("windows", "win32"):
                    rec_norm = "windows"
                elif rec_os in ("linux", "ubuntu", "debian", "fedora", "arch"):
                    rec_norm = "linux"
                elif rec_os in ("darwin", "macos", "mac"):
                    rec_norm = "darwin"
                else:
                    rec_norm = rec_os

                if cur_norm == "darwin":
                    cur_match = "darwin"
                else:
                    cur_match = cur_norm

                if rec_norm != cur_match:
                    res = SafetyGateResult(
                        allowed=False,
                        blocked_reason=BlockedReason.PLATFORM_MISMATCH,
                        is_recoverable=False,
                        message=f"Recipe specifies target OS '{recipe.os}', which does not match current host OS '{cur_os}'.",
                        details={"recipe_os": recipe.os, "host_os": cur_os},
                    )
                    self.cache.set(cache_key, res, state_sig, cur_os)
                    return res

        # Shell command prefix OS mismatch check
        cmd_lower = cmd_stripped.lower()
        if cur_os == "Windows":
            if cmd_lower.startswith(("sudo ", "apt ", "apt-get ", "dnf ", "brew ")):
                res = SafetyGateResult(
                    allowed=False,
                    blocked_reason=BlockedReason.UNSUPPORTED_METHOD,
                    is_recoverable=True,
                    message=f"Command is targeted for Linux/macOS package managers and cannot execute on Windows.",
                    details={"os": cur_os, "command": cmd_stripped},
                )
                self.cache.set(cache_key, res, state_sig, cur_os)
                return res
        elif cur_os in ("Linux", "Darwin"):
            if cmd_lower.startswith(("winget ", "choco ", "setx ", "reg ")):
                res = SafetyGateResult(
                    allowed=False,
                    blocked_reason=BlockedReason.UNSUPPORTED_METHOD,
                    is_recoverable=True,
                    message=f"Command is targeted for Windows and cannot execute on {cur_os}.",
                    details={"os": cur_os, "command": cmd_stripped},
                )
                self.cache.set(cache_key, res, state_sig, cur_os)
                return res

        # 3. Package Manager Availability Check
        pm = self._extract_pm(cmd_stripped, package_manager=package_manager)
        if pm:
            # First check machine_state normalized signal
            if machine_state is not None and getattr(machine_state, "package_manager_available", None) is False:
                res = SafetyGateResult(
                    allowed=False,
                    blocked_reason=BlockedReason.PACKAGE_MANAGER_UNAVAILABLE,
                    is_recoverable=True,
                    message=f"Required package manager '{pm}' is flagged as unavailable on this system.",
                    details={"package_manager": pm},
                )
                self.cache.set(cache_key, res, state_sig, cur_os)
                return res

            # Direct executable probe
            if not check_package_manager_available(pm):
                res = SafetyGateResult(
                    allowed=False,
                    blocked_reason=BlockedReason.PACKAGE_MANAGER_UNAVAILABLE,
                    is_recoverable=True,
                    message=f"Package manager '{pm}' is not installed or not found on PATH.",
                    details={"package_manager": pm},
                )
                self.cache.set(cache_key, res, state_sig, cur_os)
                return res

        # 4. Dependency & Concurrency Lock Check
        # 4a. Host external dependency lock
        if machine_state is not None and getattr(machine_state, "dependency_lock", None) is True:
            res = SafetyGateResult(
                allowed=False,
                blocked_reason=BlockedReason.RESOURCE_LOCKED,
                is_recoverable=True,
                message="Host system has an active package-manager or dependency lock (e.g. InProgress mutex or dpkg lock).",
                details={"dependency_lock": True},
            )
            self.cache.set(cache_key, res, state_sig, cur_os)
            return res

        # 4b. PC Doctor fine-grained resource lock manager
        try:
            from plan_freeze import resource_lock_mgr
            resources_to_check = []
            if target_resource:
                resources_to_check.append(f"tool:{target_resource.lower()}")
            if pm:
                resources_to_check.append(f"pm:{pm.lower()}")

            for r in resources_to_check:
                if resource_lock_mgr.is_locked(r):
                    # Check owner
                    owner = resource_lock_mgr._active_locks.get(r)
                    if owner_id and owner == owner_id:
                        continue # Reentrant / same owner
                    res = SafetyGateResult(
                        allowed=False,
                        blocked_reason=BlockedReason.RESOURCE_LOCKED,
                        is_recoverable=True,
                        message=f"Resource '{r}' is currently busy and locked by concurrent operation '{owner}'.",
                        details={"locked_resource": r, "owner": owner},
                    )
                    return res
        except Exception:
            pass

        # 5. Evidence-Driven Pending Reboot Policy
        if machine_state is not None and getattr(machine_state, "pending_reboot", None) is True:
            # Queries, version checks, and read-only operations are safe even during pending reboot
            is_query_or_benign = any(cmd_lower.startswith(v) or cmd_lower.endswith(v) for v in ("--version", "-version", "-v", "status", "list", "query", "info", "echo "))
            if not is_query_or_benign:
                # Check if mutating driver/firmware or system modules
                is_system_driver_mutation = any(p.search(cmd_stripped) for p in self._host_protected) or "dism" in cmd_lower or "sfc" in cmd_lower
                if is_system_driver_mutation:
                    res = SafetyGateResult(
                        allowed=False,
                        blocked_reason=BlockedReason.REQUIRES_REBOOT,
                        is_recoverable=True,
                        message="Host requires a system reboot before driver or system-level mutations can be executed.",
                        details={"pending_reboot": True},
                    )
                    return res

        # 6. Check live disk space
        free_disk_gb: Optional[float] = None
        if machine_state is not None and getattr(machine_state, "free_disk_gb", None) is not None:
            try:
                free_disk_gb = float(machine_state.free_disk_gb)
            except (ValueError, TypeError):
                free_disk_gb = None

        if free_disk_gb is None:
            if target_path is None:
                if cur_os == "Windows":
                    target_path = os.environ.get("SystemDrive", "C:") + "\\"
                else:
                    target_path = "/"
            try:
                total, used, free = shutil.disk_usage(target_path)
                free_disk_gb = round(free / (1024 ** 3), 2)
            except Exception:
                free_disk_gb = None

        if free_disk_gb is not None and free_disk_gb < required_disk_gb:
            res = SafetyGateResult(
                allowed=False,
                blocked_reason=BlockedReason.RISK_ABOVE_HARD_LIMIT,
                is_recoverable=False,
                message=f"Critically low disk space: {free_disk_gb} GB free, but minimum {required_disk_gb} GB is required.",
                details={"free_gb": free_disk_gb, "required_gb": required_disk_gb},
            )
            return res

        # 7. Check memory overload
        if _HAS_PSUTIL:
            try:
                mem = psutil.virtual_memory()
                if mem.percent >= 98.0:
                    return SafetyGateResult(
                        allowed=False,
                        blocked_reason=BlockedReason.RISK_ABOVE_HARD_LIMIT,
                        is_recoverable=False,
                        message=f"System RAM critically saturated ({mem.percent}%). Cannot execute heavy mutations safely.",
                        details={"ram_percent": mem.percent},
                    )
            except Exception:
                pass

        success_result = SafetyGateResult(
            allowed=True,
            message="Live pre-execution safety gate passed.",
            details={"is_static_recipe": is_static_recipe, "package_manager": pm},
        )
        self.cache.set(cache_key, success_result, state_sig, cur_os)
        return success_result


# Global singleton safety layer
authoritative_safety = AuthoritativeSafetyLayer()
