"""
Safety Layer – Validates commands before execution.
Blocks dangerous patterns, enforces risk thresholds, and logs decisions.
"""
import re
import platform
import os
from pathlib import Path

# Commands that are always blocked regardless of risk level
# We use [\\/]* to match both Windows backslashes and Linux slashes,
# and also handle cases where backslashes are resolved/stripped during parsing.
BLACKLIST_PATTERNS = [
    r"rm\s+-rf\s+/\s*(?:$|[\s;&|'\"])",           # rm -rf /
    r"rm\s+-rf\s+/\*",                             # rm -rf /*
    r"\b(mkfs|fdisk|parted|gparted|mkswap)\b",     # disk partitioning & formatting
    r"dd\s+if=.*of=/dev/",                         # disk wipe via dd targeting block devices
    r":\(\)\{\s*:\|:\s*&\s*\}",                    # fork bomb
    r"shutdown\s+-[hPr]?\s*now",                   # immediate shutdown
    r"reboot",
    r"(\bof=|>>?)\s*/dev/(sd[a-z]|nvme[0-9]|mem|kmem|port)", # write to raw disks/memory
    r"del.*\bwindows[\\/]*system32",               # delete System32
    r"format\s+[Cc]:",                             # format C:
    r"reg\s+delete.*HKLM[\\/]*SYSTEM",             # delete system registry keys
    r"\bmodprobe\b.*?(?:\s|^)(-(?:[a-zA-Z]*r|--remove))\b", # unloading kernel modules
    r"\brmmod\b",                                  # lower-level kernel module unloading
    r"\bsysctl\b.*?(?:\s|^)(-(?:w|-write))\b",     # altering runtime kernel parameters
]

HIGH_RISK_PATTERNS = [
    r"sudo\s+rm",
    r"chown\s+-R",
    r"chmod\s+777",
    r"sudo\s+dd",
    r"netsh\s+firewall\s+set",
    r"\bmodprobe\b",                # loading kernel modules should be a deliberate admin action
]

HOST_PROTECTED_PATTERNS = [
    r"\b(ubuntu-drivers|akmod-nvidia|nvidia-settings|xorg-x11-drv-nvidia|linux-firmware)\b",
    r"\b(kernel|kernel-core|kernel-modules|linux-generic|linux-generic-hwe|linux-image)\b",
    r"\b(systemctl)\b.*\b(enable|disable|start|stop|restart|mask|unmask)\b",
    r"\b(apt-get|apt|dnf|pacman|zypper)\b.*\b(upgrade|dist-upgrade|full-upgrade|-Syu|update)\b",
    r"\bsoftwareupdate\b.*\b(-ia|--install)\b",
    r"\bwinget\b.*\b(upgrade)\b",
]

# User-approved maintenance actions may bypass host-protected package-update blocks
# after blacklist / high-risk checks pass. Commands must match these patterns.
KERNEL_FIRMWARE_PACKAGE_PATTERNS = [
    r"\b(linux-firmware|linux-generic|linux-generic-hwe|linux-image|kernel-core|kernel-modules)\b",
    r"\b(ubuntu-drivers|akmod-nvidia|nvidia-settings|xorg-x11-drv-nvidia)\b",
]

APPROVED_MAINTENANCE_PATTERNS: dict[str, list[str]] = {
    "system_update": [
        # Combined patterns
        r"sudo\s+apt(\s+update|\-get\s+update)\s*&&\s*sudo\s+apt(\s+|-get\s+)(upgrade|dist-upgrade)(\s|$|-)",
        r"sudo\s+zypper\s+refresh\s*&&\s*sudo\s+zypper\s+update\b",
        r"brew\s+update.*brew\s+upgrade\b",
        # Individual split statement patterns
        r"sudo\s+apt(\s+update|\-get\s+update)(\s|$)",
        r"sudo\s+apt(\s+|-get\s+)(upgrade|dist-upgrade)(\s|$|-)",
        r"sudo\s+dnf\s+upgrade\b",
        r"sudo\s+pacman\s+-Syu\b",
        r"sudo\s+zypper\s+refresh\b",
        r"sudo\s+zypper\s+update\b",
        r"winget\s+upgrade\b",
        r"softwareupdate\s+-ia\b",
        r"brew\s+update\b",
        r"brew\s+upgrade\b",
    ],
    "remove_orphans": [
        r"sudo\s+apt(\-get)?\s+autoremove\b",
        r"sudo\s+dnf\s+autoremove\b",
        r"sudo\s+pacman\s+-Rns\b",
        r"sudo\s+zypper\s+clean\b",
        r"brew\s+autoremove\b",
    ],
    # Driver package updates — triggered explicitly from the Drivers page.
    # Allows OS package-manager driver update commands to pass host-protection
    # when action_key='driver_package_update' is set by the frontend.
    "driver_package_update": [
        r"winget\s+upgrade\b",
        r"winget\s+upgrade\s+--all\b",
        r"sudo\s+apt(\-get)?.*install.*linux-firmware\b",
        r"sudo\s+apt(\-get)?.*install.*linux-generic\b",
        r"sudo\s+apt(\-get)?.*upgrade.*linux\b",
        r"sudo\s+dnf\s+upgrade\b",
        r"sudo\s+pacman\s+-Syu\b",
        r"softwareupdate\s+-ia\b",
        r"sudo\s+ubuntu-drivers\s+autoinstall\b",
        r"sudo\s+dnf\s+install.*akmod-nvidia\b",
    ],
}


def _running_in_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="ignore").lower()
        return "docker" in cgroup or "containerd" in cgroup or "kubepods" in cgroup
    except Exception:
        return False


def split_commands_and_args(cmd: str) -> list[list[str]]:
    """
    Parses a shell command line into individual subcommands, respecting single/double quotes,
    backslash escapes, and all statement operators (;, &&, ||, |, &) even if unspaced.
    """
    statements = []
    current_statement = []
    current_token = []
    
    in_single_quote = False
    in_double_quote = False
    escaped = False
    
    is_windows_host = platform.system() == "Windows"
    
    i = 0
    n = len(cmd)
    
    while i < n:
        char = cmd[i]
        
        if escaped:
            current_token.append(char)
            escaped = False
            i += 1
            continue
            
        if char == '\\' and not in_single_quote and not is_windows_host:
            escaped = True
            i += 1
            continue
            
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            i += 1
            continue
            
        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            i += 1
            continue
            
        if in_single_quote or in_double_quote:
            current_token.append(char)
            i += 1
            continue
            
        # Outside quotes/escapes: check for delimiters and whitespace
        # 1. Delimiters (&&, ||)
        if i + 1 < n and cmd[i:i+2] in ("&&", "||"):
            if current_token:
                current_statement.append("".join(current_token))
                current_token = []
            if current_statement:
                statements.append(current_statement)
                current_statement = []
            i += 2
            continue
            
        # 2. Delimiters (;, |, &)
        if char in (";", "|", "&"):
            if current_token:
                current_statement.append("".join(current_token))
                current_token = []
            if current_statement:
                statements.append(current_statement)
                current_statement = []
            i += 1
            continue
            
        # 3. Whitespace
        if char.isspace():
            if current_token:
                current_statement.append("".join(current_token))
                current_token = []
            i += 1
            continue
            
        # 4. Standard character
        current_token.append(char)
        i += 1
        
    if current_token:
        current_statement.append("".join(current_token))
    if current_statement:
        statements.append(current_statement)
        
    return statements


def extract_executable_and_args(stmt: list[str]) -> tuple[str, list[str]]:
    """
    Isolates the target executable and its arguments from a command statement,
    resolving prepended environment variables (e.g. VAR=val) and sudo/pkexec wrappers.
    """
    if not stmt:
        return "", []
        
    start_idx = 0
    while start_idx < len(stmt) and "=" in stmt[start_idx] and not stmt[start_idx].startswith("-"):
        parts = stmt[start_idx].split("=", 1)
        if parts[0].isidentifier():
            start_idx += 1
        else:
            break
            
    if start_idx >= len(stmt):
        return "", []
        
    exec_idx = start_idx
    while exec_idx < len(stmt) and stmt[exec_idx] in ("sudo", "pkexec"):
        exec_idx += 1
        
    if exec_idx >= len(stmt):
        return stmt[start_idx], stmt[start_idx+1:]
        
    return stmt[exec_idx], stmt[exec_idx+1:]


def extract_subshells(cmd: str) -> list[str]:
    subshells = []
    i = 0
    n = len(cmd)
    while i < n:
        if cmd[i:i+2] == "$(":
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                if cmd[j] == '(':
                    depth += 1
                elif cmd[j] == ')':
                    depth -= 1
                    if depth == 0:
                        subshells.append(cmd[i+2:j])
                        break
                j += 1
            i = j
        elif cmd[i] == '`':
            j = i + 1
            while j < n:
                if cmd[j] == '`' and cmd[j-1] != '\\':
                    subshells.append(cmd[i+1:j])
                    break
                j += 1
            i = j
        i += 1
    return subshells


def is_blocked_script_execution(token: str) -> bool:
    token_lower = token.lower()
    # Check for direct local invocation
    if token_lower.startswith("./") or token_lower.startswith("../") or token_lower.startswith(".\\") or token_lower.startswith("..\\"):
        return True
    
    # Check for executable path under typical writable regions
    writable_paths = ("/home/", "/tmp/", "/var/tmp/", "c:\\users\\", "c:\\windows\\temp\\", "%temp%", "%tmp%")
    script_extensions = (".sh", ".bash", ".py", ".js", ".ps1", ".bat", ".cmd")
    
    has_writable_prefix = any(p in token_lower for p in writable_paths)
    has_script_suffix = any(token_lower.endswith(ext) for ext in script_extensions)
    
    if has_writable_prefix and has_script_suffix:
        return True
        
    return False


def log_safety_override(action: str, original_result: str, reason: str):
    import sqlite3
    import datetime
    try:
        from self_healing import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS safety_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                original_safety_result TEXT NOT NULL,
                override_reason TEXT NOT NULL
            )
        """)
        conn.commit()
        cur.execute("""
            INSERT INTO safety_overrides (timestamp, action, original_safety_result, override_reason)
            VALUES (?, ?, ?, ?)
        """, (
            datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
            action,
            original_result,
            reason
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        try:
            from logger import log_action
            log_action("ERROR", "log_safety_override", f"Failed to log override: {e}")
        except Exception:
            pass


class SafetyLayer:
    """
    Returns (blocked: bool, reason: str) for a given (command, risk_level).
    blocked=True means the command must NOT be executed.
    """

    def __init__(self):
        # Pre-compile regex patterns for maximum efficiency during validation
        self.blacklist = [re.compile(p, re.IGNORECASE) for p in BLACKLIST_PATTERNS]
        self.high_risk = [re.compile(p, re.IGNORECASE) for p in HIGH_RISK_PATTERNS]
        self.host_protected = [re.compile(p, re.IGNORECASE) for p in HOST_PROTECTED_PATTERNS]
        self.linux_only = [re.compile(p, re.IGNORECASE) for p in [r"^\s*sudo\b", r"^\s*apt\b", r"^\s*dnf\b", r"^\s*pacman\b"]]
        self.windows_only = [re.compile(p, re.IGNORECASE) for p in [r"^\s*winget\b", r"^\s*choco\b", r"^\s*setx\b", r"^\s*reg\b"]]
        self.macos_only = [re.compile(p, re.IGNORECASE) for p in [r"^\s*brew\b", r"^\s*softwareupdate\b", r"^\s*osascript\b", r"^\s*purge\b"]]

    def _matches_approved_maintenance(self, command: str, action_key: str) -> bool:
        patterns = APPROVED_MAINTENANCE_PATTERNS.get(action_key, [])
        if not patterns:
            return False
        compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
        return any(pattern.search(command) for pattern in compiled)

    def explain_block(self, command: str, risk: str = "Low", action_key: str | None = None) -> dict[str, str]:
        blocked, reason = self.validate(command, risk, action_key=action_key)
        result = {
            "blocked": str(blocked).lower(),
            "command": command,
            "reason": reason,
            "recommended_fix": "",
        }
        if not blocked:
            result["recommended_fix"] = "Command passed safety validation."
            return result
        lower = reason.lower()
        if action_key == "system_update" or "safe mode blocked" in lower:
            result["recommended_fix"] = (
                "Package updates are blocked by host-protection safe mode unless the command "
                "matches an approved OS package-manager update pattern and is run with explicit "
                "user approval from Optimize. Ensure the adapted command matches your package "
                "manager (apt, dnf, pacman, zypper, winget, or softwareupdate)."
            )
        elif "high-risk" in lower or "blocked for safety" in lower:
            result["recommended_fix"] = "Use a safer maintenance command or run it manually outside PC Doc."
        elif "linux-only" in lower or "windows-only" in lower or "macos-only" in lower:
            result["recommended_fix"] = "Refresh OS adaptation so PC Doc selects a command for your current operating system."
        return result

    def validate(self, command: str, risk: str = "Low", action_key: str | None = None) -> tuple[bool, str]:
        blocked, reason = self._validate_internal(command, risk, action_key)
        if blocked:
            from feature_flags import ENABLE_DEV_MODE
            if ENABLE_DEV_MODE:
                log_safety_override(command, f"Blocked: {reason}", "DEVELOPMENT_MODE Safety Bypass")
                return False, f"WARNING: {reason}"
        return blocked, reason

    def _validate_internal(self, command: str, risk: str = "Low", action_key: str | None = None) -> tuple[bool, str]:
        cmd_stripped = command.strip()
        if not cmd_stripped:
            return True, "Empty command."

        # Check subshells recursively to prevent nested command execution bypasses
        subshells = extract_subshells(command)
        for sub in subshells:
            blocked, reason = self.validate(sub, risk, action_key)
            if blocked:
                return True, f"Blocked subshell execution: {reason}"

        statements = split_commands_and_args(command)
        if not statements:
            return True, "Empty command."

        current_os = platform.system()
        is_windows = current_os == "Windows"
        is_macos = current_os == "Darwin"
        
        safe_mode = os.getenv("PC_DOCTOR_SAFE_MODE", "").lower() in {"1", "true", "yes"}
        allow_host_system_changes = os.getenv("PC_DOCTOR_ALLOW_HOST_SYSTEM_CHANGES", "").lower() in {"1", "true", "yes"}

        for stmt in statements:
            if not stmt:
                continue
            stmt_str = " ".join(stmt)
            stmt_lower = stmt_str.lower()
            
            # Extract executable and arguments for granular safety logic
            exe, args = extract_executable_and_args(stmt)
            exe_lower = exe.lower()

            # Block executing script files located in user-writable regions
            if is_blocked_script_execution(exe):
                return True, f"Executing local scripts (`{exe}`) is blocked for safety."
            for arg in args:
                if is_blocked_script_execution(arg):
                    return True, f"Executing script file `{arg}` in writable directory is blocked."

            # 1. Hard blacklist – always block
            for pattern in self.blacklist:
                if pattern.search(stmt_str):
                    return True, f"Command matches dangerous pattern: `{pattern.pattern}`"

            # 2. Blacklisted binaries isolation
            BLACKLIST_BINARIES = {
                "mkfs", "fdisk", "parted", "gparted", "mkswap", "dd", "rmmod", "format", "reboot", "shutdown"
            }
            if exe_lower in BLACKLIST_BINARIES:
                return True, f"Command execution of binary `{exe}` is blocked for safety."

            # Specific arguments isolation: check for rm -rf / or sensitive paths
            if exe_lower == "rm":
                has_force = any(arg.startswith("-") and "f" in arg for arg in args)
                has_recursive = any(arg.startswith("-") and ("r" in arg or "R" in arg) for arg in args)
                if has_force or has_recursive:
                    for arg in args:
                        if arg in ("/", "/*", "/etc", "/etc/", "/boot", "/boot/", "/var", "/var/", "/usr", "/usr/"):
                            return True, f"Destructive directory removal of `{arg}` is blocked."

            # 3. High-risk patterns – always block in automated repair
            for pattern in self.high_risk:
                if pattern.search(stmt_str):
                    return True, "This command is high-risk. It is not permitted through the automated repair engine."

            # 4. Check if statement matches approved maintenance for this action_key
            is_approved = False
            if action_key and self._matches_approved_maintenance(stmt_str, action_key):
                # driver_package_update is explicitly user-initiated from the Drivers page.
                # Allow kernel/firmware packages for that action key only.
                if action_key != "driver_package_update":
                    for pattern in KERNEL_FIRMWARE_PACKAGE_PATTERNS:
                        if re.search(pattern, stmt_lower, re.IGNORECASE):
                            return True, "Kernel, firmware, or driver package updates are not permitted through the approved system update action."
                is_approved = True

            # Enforce safe mode / host protection if not explicitly approved
            if not is_approved:
                if safe_mode or (not _running_in_container() and not allow_host_system_changes):
                    for pattern in self.host_protected:
                        if pattern.search(stmt_str):
                            return True, (
                                "Safe mode blocked a kernel, driver, service, or full-system "
                                "update command. Approved package updates from Optimize are allowed "
                                "when they match your OS package manager. Kernel or firmware-only "
                                "updates remain blocked unless PC_DOCTOR_ALLOW_HOST_SYSTEM_CHANGES=1."
                            )

            # 5. OS mismatch guard
            if is_windows:
                for pattern in self.linux_only:
                    if pattern.search(stmt_str):
                        return True, "Linux-only command detected on Windows."
                for pattern in self.macos_only:
                    if pattern.search(stmt_str):
                        return True, "macOS-only command detected on Windows."
            elif is_macos:
                for pattern in self.linux_only:
                    if pattern.search(stmt_str):
                        return True, "Linux-only command detected on macOS."
                for pattern in self.windows_only:
                    if pattern.search(stmt_str):
                        return True, "Windows-only command detected on macOS."
            else:  # Linux
                for pattern in self.windows_only:
                    if pattern.search(stmt_str):
                        return True, "Windows-only command detected on Linux."
                for pattern in self.macos_only:
                    if pattern.search(stmt_str):
                        return True, "macOS-only command detected on Linux."

        return False, "OK"
