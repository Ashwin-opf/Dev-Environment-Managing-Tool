"""
System Scanner — Detects health issues across OS, dev tools, and hardware.
Each check returns a dict: {type, severity, title, detail, recipe_hint}
"""
import os
import platform
import shutil
import subprocess
import psutil
import re
import time
from pathlib import Path
from typing import Any, List, Dict, Optional, Set


# Cross-platform subprocess wrapper — always decodes output as UTF-8.
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


SEVERITY_LOW = "low"
SEVERITY_MEDIUM = "medium"
SEVERITY_HIGH = "high"

# TTL cache for expensive scan steps (step_id -> (timestamp, result))
_STEP_CACHE: Dict[str, tuple] = {}
_STEP_CACHE_TTL = 60  # seconds


def _get_cached(step_id: str):
    """Return cached result if still fresh, else None."""
    entry = _STEP_CACHE.get(step_id)
    if entry:
        ts, result = entry
        if time.monotonic() - ts < _STEP_CACHE_TTL:
            return result
    return None


def _set_cached(step_id: str, result: list):
    _STEP_CACHE[step_id] = (time.monotonic(), result)


class SystemScanner:
    def __init__(self):
        self.latest_issues = []
        self._scan_completed = False
        self.resolved_types = set()

    def get_steps(self) -> List[Dict[str, str]]:
        return [
            {"id": "memory", "title": "Memory Health Check"},
            {"id": "storage", "title": "Storage Health Check"},
            {"id": "cpu", "title": "CPU Load Check"},
            {"id": "services", "title": "Failed Services Check"},
            {"id": "gpu_drivers", "title": "GPU & Drivers Check"},
            {"id": "repositories", "title": "Repository Integrity Check"},
            {"id": "os_updates", "title": "System Updates Check"},
            {"id": "dev_tools", "title": "Developer Environment Check"}
        ]

    def invalidate_cache(self, step_id: Optional[str] = None) -> None:
        """Invalidates TTL cache for a step or all steps."""
        global _STEP_CACHE
        if step_id:
            _STEP_CACHE.pop(step_id, None)
        else:
            _STEP_CACHE.clear()

    def remove_issue(self, issue_type_or_title: str) -> None:
        """Purges an issue from latest_issues and marks it resolved."""
        if hasattr(self, "latest_issues") and isinstance(self.latest_issues, list):
            self.latest_issues = [
                x for x in self.latest_issues
                if x.get("type") != issue_type_or_title and x.get("title") != issue_type_or_title
            ]
        if hasattr(self, "resolved_types"):
            self.resolved_types.add(issue_type_or_title)

    def run_step(self, step_id: str) -> List[Dict[str, Any]]:
        """Run a single scanning step by ID. Uses TTL cache for expensive steps."""
        # Return cached result if fresh
        cached = _get_cached(step_id)
        if cached is not None:
            # Still apply resolved_types filter on cached results
            res = cached
            if hasattr(self, "resolved_types") and self.resolved_types:
                res = [x for x in res if x.get("type") not in self.resolved_types and x.get("recipe_hint") not in self.resolved_types]
            res_types = {x["type"] for x in res}
            self.latest_issues = [x for x in self.latest_issues if x["type"] not in res_types and x["type"] not in self.resolved_types] + res
            return res

        res = []
        if step_id == "memory":
            res = self._check_memory()
        elif step_id == "storage":
            res = self._check_disk()
        elif step_id == "cpu":
            res = self._check_cpu()
        elif step_id == "services":
            if platform.system() == "Linux":
                res = self._check_linux_services()
            elif platform.system() == "Windows":
                res = self._check_windows_update()
        elif step_id == "gpu_drivers":
            if platform.system() == "Linux":
                res = self._check_gpu_drivers()
            elif platform.system() == "Windows":
                res = self._check_windows_drivers()
        elif step_id == "repositories":
            res = self._check_repositories()
        elif step_id == "os_updates":
            res = self._check_system_updates()
        elif step_id == "dev_tools":
            res = self._check_devtools()

        # Cache the raw result before filtering
        _set_cached(step_id, res)

        # Filter out resolved types/hints
        if hasattr(self, "resolved_types") and self.resolved_types:
            res = [x for x in res if x.get("type") not in self.resolved_types and x.get("recipe_hint") not in self.resolved_types]

        self._scan_completed = True
        res_types = {x["type"] for x in res}
        self.latest_issues = [x for x in self.latest_issues if x["type"] not in res_types and x["type"] not in self.resolved_types] + res
        return res

    def scan(self, core: bool = True, dev: bool = True) -> list[dict[str, Any]]:
        """Run system scan with configurable scope."""
        issues = []
        if core:
            issues += self._check_memory()
            issues += self._check_disk()
            issues += self._check_cpu()
            issues += self._check_repositories()
            if platform.system() == "Linux":
                issues += self._check_linux_services()
                issues += self._check_gpu_drivers()
                issues += self._check_system_updates()
            elif platform.system() == "Windows":
                issues += self._check_windows_update()
                issues += self._check_windows_drivers()

        if dev:
            issues += self._check_devtools()

        if hasattr(self, "resolved_types") and self.resolved_types:
            issues = [x for x in issues if x.get("type") not in self.resolved_types and x.get("recipe_hint") not in self.resolved_types]

        self._scan_completed = True
        self.latest_issues = issues
        return issues

    # ── Hardware ──────────────────────────────────────────────────────────────
    def _check_memory(self) -> list:
        mem = psutil.virtual_memory()
        issues = []
        available_gb = mem.available / 1024**3
        if available_gb < 1.0:
            issues.append({
                "type": "memory",
                "severity": SEVERITY_HIGH,
                "title": "Critical: Very Low Available RAM",
                "detail": f"Only {available_gb:.1f} GB RAM available. System may be unstable.",
                "recipe_hint": "boost_ram",
            })
        elif available_gb < 2.0:
            issues.append({
                "type": "memory",
                "severity": SEVERITY_MEDIUM,
                "title": "Low Available RAM",
                "detail": f"{available_gb:.1f} GB RAM available. Consider closing unused applications.",
                "recipe_hint": "boost_ram",
            })
        return issues

    def _check_disk(self) -> list:
        issues = []
        try:
            partitions = psutil.disk_partitions(all=False)
            for p in partitions:
                try:
                    usage = psutil.disk_usage(p.mountpoint)
                    pct = usage.percent
                    free_gb = usage.free / 1024**3
                    if pct >= 95:
                        issues.append({
                            "type": f"disk_full_{p.device.replace(':', '').replace('\\', '').replace('/', '')}",
                            "severity": SEVERITY_HIGH,
                            "title": f"Critical: Disk Almost Full ({p.mountpoint})",
                            "detail": f"Drive {p.mountpoint} is {pct:.0f}% full ({free_gb:.1f} GB free). System may become unstable.",
                            "recipe_hint": "free_disk_space",
                        })
                    elif pct >= 85:
                        issues.append({
                            "type": f"disk_low_{p.device.replace(':', '').replace('\\', '').replace('/', '')}",
                            "severity": SEVERITY_MEDIUM,
                            "title": f"Low Disk Space ({p.mountpoint})",
                            "detail": f"Drive {p.mountpoint} is {pct:.0f}% full ({free_gb:.1f} GB free).",
                            "recipe_hint": "free_disk_space",
                        })
                except (PermissionError, OSError):
                    pass
        except Exception:
            pass
        return issues

    def _check_cpu(self) -> list:
        issues = []
        try:
            # Use a short interval (0.1s) instead of blocking for 1s
            cpu_pct = psutil.cpu_percent(interval=0.1)
            if cpu_pct > 95:
                issues.append({
                    "type": "cpu_critical",
                    "severity": SEVERITY_HIGH,
                    "title": "Critical CPU Load",
                    "detail": f"CPU usage is at {cpu_pct:.0f}%. System responsiveness severely impacted.",
                    "recipe_hint": "cpu_usage",
                })
            elif cpu_pct > 80:
                issues.append({
                    "type": "cpu_high",
                    "severity": SEVERITY_MEDIUM,
                    "title": "High CPU Usage",
                    "detail": f"CPU usage is at {cpu_pct:.0f}%. Consider closing heavy applications.",
                    "recipe_hint": "cpu_usage",
                })
        except Exception:
            pass
        return issues

    def _check_repositories(self) -> list:
        issues = []
        sys_name = platform.system()

        if sys_name == "Linux":
            sources_path = Path("/etc/apt/sources.list")
            sources_dir = Path("/etc/apt/sources.list.d")

            try:
                res = _safe_run(["apt-get", "check"], timeout=4)
                if res.returncode != 0:
                    err = res.stderr.lower()
                    if "permission denied" not in err and "are you root" not in err:
                        issues.append({
                            "type": "repository",
                            "severity": SEVERITY_HIGH,
                            "title": "Package Repository DB Locked",
                            "detail": f"Package manager database verification failed: {res.stderr.strip()}",
                            "recipe_hint": "fix_apt_locks"
                        })
            except Exception:
                pass

            if sources_path.exists():
                try:
                    content = sources_path.read_text(encoding="utf-8", errors="ignore")
                    if "unreachable" in content.lower():
                        issues.append({
                            "type": "repository",
                            "severity": SEVERITY_MEDIUM,
                            "title": "Invalid Repository Mirror configured",
                            "detail": "Your /etc/apt/sources.list contains an invalid or offline mirror link.",
                            "recipe_hint": "refresh_commands"
                        })
                except Exception:
                    pass

        elif sys_name == "Windows":
            if shutil.which("winget"):
                try:
                    # Reduced timeout: winget source list can be slow on first run
                    res = _safe_run(["winget", "source", "list"], timeout=4)
                    if res.returncode != 0 or "failed" in res.stdout.lower() or "unhealthy" in res.stdout.lower():
                        issues.append({
                            "type": "repository",
                            "severity": SEVERITY_MEDIUM,
                            "title": "Winget Package Source Integrity Issue",
                            "detail": "One or more Winget package repository sources are unhealthy or failed to respond.",
                            "recipe_hint": "winget source reset --force"
                        })
                except Exception:
                    pass
        elif sys_name == "Darwin":
            if shutil.which("brew"):
                try:
                    res = _safe_run(["brew", "doctor"], timeout=8)
                    if "error" in res.stdout.lower() or res.returncode != 0:
                        issues.append({
                            "type": "repository",
                            "severity": SEVERITY_MEDIUM,
                            "title": "Homebrew Doctor Warnings",
                            "detail": "Homebrew has detected system package manager warning states.",
                            "recipe_hint": "brew update"
                        })
                except Exception:
                    pass
        return issues

    def _check_system_updates(self) -> list:
        issues = []
        if platform.system() == "Linux":
            try:
                res = _safe_run(["apt-get", "-s", "upgrade"], timeout=5)
                match = re.search(r'(\d+)\s+upgraded,\s+(\d+)\s+newly\s+installed', res.stdout)
                if match:
                    upgraded = int(match.group(1))
                    if upgraded > 0:
                        issues.append({
                            "type": "updates",
                            "severity": SEVERITY_LOW,
                            "title": "System Updates Available",
                            "detail": f"There are {upgraded} system package updates ready for installation.",
                            "recipe_hint": "system_update"
                        })
            except Exception:
                pass
        return issues

    # ── Windows Update & Platform Checks ──────────────────────────────────────
    def _check_windows_update(self) -> list:
        issues = []
        if platform.system() != "Windows":
            return issues
        try:
            from dev_environment_detector import dev_environment_detector
            svc = dev_environment_detector.check_service("wuauserv")
            if svc.get("exists") and svc.get("status") == "Stopped":
                issues.append({
                    "type": "service_wuauserv",
                    "severity": SEVERITY_MEDIUM,
                    "title": "Windows Update Agent Stopped",
                    "detail": "The Windows Update service (wuauserv) is inactive. Updates cannot be retrieved.",
                    "recipe_hint": 'powershell -Command "Start-Service wuauserv"',
                    "fix_command": 'powershell -Command "Start-Service wuauserv"',
                    "category": "Services",
                })
        except Exception:
            pass
        return issues

    def _check_windows_drivers(self) -> list:
        issues = []
        if platform.system() != "Windows":
            return issues
        try:
            # -NoProfile -NonInteractive cuts PowerShell cold-start from ~5s to ~1s
            res = _safe_run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-PnpDevice -Status Error | Select-Object -ExpandProperty FriendlyName"],
                timeout=4
            )
            devices = [d.strip() for d in res.stdout.splitlines() if d.strip()]
            if devices:
                issues.append({
                    "type": "driver_windows_error",
                    "severity": SEVERITY_HIGH,
                    "title": "Hardware Device Driver Error",
                    "detail": f"Windows PNP reported driver error status on: {', '.join(devices[:3])}.",
                    "recipe_hint": "winget upgrade"
                })
        except Exception:
            pass
        return issues

    # ── Authoritative General Developer Environment Detection ────────────────
    def _check_devtools(self) -> list:
        issues = []
        try:
            from dev_environment_detector import dev_environment_detector, ToolHealthStatus
            diagnoses = dev_environment_detector.diagnose_all_tools()
            for diag in diagnoses:
                if diag.status in (ToolHealthStatus.INSTALLED_AND_USABLE, ToolHealthStatus.NOT_INSTALLED):
                    continue

                if diag.status == ToolHealthStatus.INSTALLED_BUT_PATH_MISSING:
                    title = f"{diag.display_name} Installed But Missing From PATH"
                    sev = SEVERITY_MEDIUM
                elif diag.status == ToolHealthStatus.SERVICE_INSTALLED_BUT_STOPPED:
                    title = f"{diag.display_name} Service Stopped"
                    sev = SEVERITY_MEDIUM
                elif diag.status == ToolHealthStatus.PORT_CONFLICT:
                    title = f"{diag.display_name} Port Conflict (Port {diag.port_conflict})"
                    sev = SEVERITY_MEDIUM
                elif diag.status == ToolHealthStatus.MULTIPLE_VERSIONS:
                    title = f"Multiple {diag.display_name} Versions In PATH"
                    sev = SEVERITY_LOW
                elif diag.status == ToolHealthStatus.EXECUTABLE_EXISTS_BUT_VERIFICATION_FAILED:
                    title = f"{diag.display_name} Executable Corrupted Or Verification Failed"
                    sev = SEVERITY_HIGH
                elif diag.status == ToolHealthStatus.PACKAGE_MANAGER_STATE_MISMATCH:
                    title = f"{diag.display_name} Package Manager Registration Mismatch"
                    sev = SEVERITY_MEDIUM
                else:
                    title = f"{diag.display_name} Configuration Issue"
                    sev = SEVERITY_MEDIUM

                issues.append({
                    "type": f"tool_health_{diag.tool_id}_{diag.status.value.lower()}",
                    "severity": sev,
                    "title": title,
                    "detail": diag.diagnosis_message,
                    "recipe_hint": None,
                    "fix_command": diag.repair_command,
                    "recommended_action": diag.recommended_action,
                    "automatic_repair": diag.automatic_repair,
                    "category": "Developer Environment",
                    "tool_id": diag.tool_id,
                    "issue_status": diag.status.value,
                    "requires_elevation": diag.requires_elevation,
                    "scope": diag.path_scope,
                    "repairability": "AUTOMATIC_WITH_ELEVATION" if diag.requires_elevation else ("AUTOMATIC" if diag.repair_command and diag.automatic_repair else "REVIEW_REQUIRED"),
                })
        except Exception as exc:
            pass
        return issues

    def _check_python(self) -> list:
        from dev_environment_detector import dev_environment_detector, ToolHealthStatus
        diag = dev_environment_detector.diagnose_tool("python")
        if diag.status in (ToolHealthStatus.INSTALLED_AND_USABLE, ToolHealthStatus.NOT_INSTALLED):
            return []
        return [{
            "type": "python_path",
            "severity": SEVERITY_MEDIUM,
            "title": f"Python Health Issue: {diag.status.value}",
            "detail": diag.diagnosis_message,
            "recipe_hint": None,
            "fix_command": diag.repair_command,
            "recommended_action": diag.recommended_action,
            "automatic_repair": diag.automatic_repair,
            "requires_elevation": diag.requires_elevation,
            "scope": diag.path_scope,
            "repairability": "AUTOMATIC_WITH_ELEVATION" if diag.requires_elevation else ("AUTOMATIC" if diag.repair_command and diag.automatic_repair else "REVIEW_REQUIRED"),
        }]

    def _check_node(self) -> list:
        from dev_environment_detector import dev_environment_detector, ToolHealthStatus
        diag = dev_environment_detector.diagnose_tool("nodejs")
        if diag.status in (ToolHealthStatus.INSTALLED_AND_USABLE, ToolHealthStatus.NOT_INSTALLED):
            return []
        return [{
            "type": "node_health",
            "severity": SEVERITY_MEDIUM,
            "title": f"Node.js Health Issue: {diag.status.value}",
            "detail": diag.diagnosis_message,
            "recipe_hint": None,
            "fix_command": diag.repair_command,
            "recommended_action": diag.recommended_action,
            "automatic_repair": diag.automatic_repair,
            "requires_elevation": diag.requires_elevation,
            "scope": diag.path_scope,
            "repairability": "AUTOMATIC_WITH_ELEVATION" if diag.requires_elevation else ("AUTOMATIC" if diag.repair_command and diag.automatic_repair else "REVIEW_REQUIRED"),
        }]

    def _check_git(self) -> list:
        from dev_environment_detector import dev_environment_detector, ToolHealthStatus
        diag = dev_environment_detector.diagnose_tool("git")
        if diag.status in (ToolHealthStatus.INSTALLED_AND_USABLE, ToolHealthStatus.NOT_INSTALLED):
            return []
        return [{
            "type": "git_path",
            "severity": SEVERITY_MEDIUM,
            "title": f"Git Health Issue: {diag.status.value}",
            "detail": diag.diagnosis_message,
            "recipe_hint": None,
            "fix_command": diag.repair_command,
            "recommended_action": diag.recommended_action,
            "automatic_repair": diag.automatic_repair,
            "requires_elevation": diag.requires_elevation,
            "scope": diag.path_scope,
            "repairability": "AUTOMATIC_WITH_ELEVATION" if diag.requires_elevation else ("AUTOMATIC" if diag.repair_command and diag.automatic_repair else "REVIEW_REQUIRED"),
        }]

    def _check_docker(self) -> list:
        from dev_environment_detector import dev_environment_detector, ToolHealthStatus
        diag = dev_environment_detector.diagnose_tool("docker")
        if diag.status in (ToolHealthStatus.INSTALLED_AND_USABLE, ToolHealthStatus.NOT_INSTALLED):
            return []
        return [{
            "type": "docker_stopped",
            "severity": SEVERITY_MEDIUM,
            "title": f"Docker Health Issue: {diag.status.value}",
            "detail": diag.diagnosis_message,
            "recipe_hint": None,
            "fix_command": diag.repair_command,
            "recommended_action": diag.recommended_action,
            "automatic_repair": diag.automatic_repair,
            "requires_elevation": diag.requires_elevation,
            "scope": diag.path_scope,
            "repairability": "AUTOMATIC_WITH_ELEVATION" if diag.requires_elevation else ("AUTOMATIC" if diag.repair_command and diag.automatic_repair else "REVIEW_REQUIRED"),
        }]

    def _check_java(self) -> list:
        from dev_environment_detector import dev_environment_detector, ToolHealthStatus
        diag = dev_environment_detector.diagnose_tool("java")
        if diag.status in (ToolHealthStatus.INSTALLED_AND_USABLE, ToolHealthStatus.NOT_INSTALLED):
            return []
        return [{
            "type": "java_health",
            "severity": SEVERITY_MEDIUM,
            "title": f"Java Health Issue: {diag.status.value}",
            "detail": diag.diagnosis_message,
            "recipe_hint": None,
            "fix_command": diag.repair_command,
            "recommended_action": diag.recommended_action,
            "automatic_repair": diag.automatic_repair,
            "requires_elevation": diag.requires_elevation,
            "scope": diag.path_scope,
            "repairability": "AUTOMATIC_WITH_ELEVATION" if diag.requires_elevation else ("AUTOMATIC" if diag.repair_command and diag.automatic_repair else "REVIEW_REQUIRED"),
        }]

    def _check_vscode(self) -> list:
        from dev_environment_detector import dev_environment_detector, ToolHealthStatus
        diag = dev_environment_detector.diagnose_tool("vscode")
        if diag.status in (ToolHealthStatus.INSTALLED_AND_USABLE, ToolHealthStatus.NOT_INSTALLED):
            return []
        return [{
            "type": "vscode_health",
            "severity": SEVERITY_MEDIUM,
            "title": f"VS Code Health Issue: {diag.status.value}",
            "detail": diag.diagnosis_message,
            "recipe_hint": None,
            "fix_command": diag.repair_command,
            "recommended_action": diag.recommended_action,
            "automatic_repair": diag.automatic_repair,
            "requires_elevation": diag.requires_elevation,
            "scope": diag.path_scope,
            "repairability": "AUTOMATIC_WITH_ELEVATION" if diag.requires_elevation else ("AUTOMATIC" if diag.repair_command and diag.automatic_repair else "REVIEW_REQUIRED"),
        }]

    def _check_linux_services(self) -> list:
        issues = []
        try:
            res = _safe_run(["systemctl", "--failed", "--type=service", "--quiet"], timeout=4)
            res_list = _safe_run(["systemctl", "list-units", "--state=failed", "--type=service", "--no-legend"], timeout=4)
            failed_lines = [l.strip() for l in res_list.stdout.splitlines() if l.strip()]
            for line in failed_lines:
                svc_name = line.split()[0]
                issues.append({
                    "type": f"service_failed_{svc_name}",
                    "severity": SEVERITY_HIGH,
                    "title": f"Systemd Service Failed: {svc_name}",
                    "detail": f"Service `{svc_name}` has entered a failed state and requires restarting.",
                    "recipe_hint": f"sudo systemctl restart {svc_name}"
                })
        except Exception:
            pass

        services = ["cron", "NetworkManager"]
        for svc in services:
            try:
                result = _safe_run(["systemctl", "is-active", svc], timeout=3)
                status = result.stdout.strip()
                if status not in ("active",):
                    if not any(f"service_failed_{svc}" in issue["type"] for issue in issues):
                        issues.append({
                            "type": f"service_{svc}",
                            "severity": SEVERITY_LOW,
                            "title": f"Service Not Active: {svc}",
                            "detail": f"`{svc}` status is `{status}`. It may need to be started.",
                            "recipe_hint": f"sudo systemctl start {svc}",
                        })
            except Exception:
                pass
        return issues

    def _check_gpu_drivers(self) -> list:
        issues = []
        if platform.system() != "Linux":
            return issues

        try:
            lspci_cmd = "lspci -nn | grep -i -E 'vga|3d|display'"
            gpu_res = _safe_run(lspci_cmd, shell=True, timeout=4)
            has_nvidia = "nvidia" in gpu_res.stdout.lower() or "geforce" in gpu_res.stdout.lower()

            lsmod_res = _safe_run("lsmod | grep nouveau", shell=True, timeout=3)
            using_nouveau = "nouveau" in lsmod_res.stdout.lower()

            nvidia_loaded = False
            try:
                nvidia_res = _safe_run("lsmod | grep nvidia", shell=True, timeout=3)
                nvidia_loaded = "nvidia" in nvidia_res.stdout.lower()
            except Exception:
                pass

            if has_nvidia and (using_nouveau or not nvidia_loaded):
                issues.append({
                    "type": "gpu_drivers",
                    "severity": SEVERITY_MEDIUM,
                    "title": "Generic GPU Driver Active",
                    "detail": "Your Nvidia graphics card is using open-source generic drivers. High-performance proprietary drivers are available.",
                    "recipe_hint": "install_nvidia_drivers",
                })
        except Exception:
            pass
        return issues


# Global singleton instance
scanner = SystemScanner()

