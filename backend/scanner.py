"""
System Scanner â€“ Detects health issues across OS, dev tools, and hardware.
Each check returns a dict: {type, severity, title, detail, recipe_hint}
"""
import os
import platform
import shutil
import subprocess
import psutil
import re
from pathlib import Path
from typing import Any, List, Dict


# Cross-platform subprocess wrapper â€“ always decodes output as UTF-8.
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

    def run_step(self, step_id: str) -> List[Dict[str, Any]]:
        """Run a single scanning step by ID."""
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
            res = self._check_python() + self._check_docker()
            
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
            issues += self._check_python()
            issues += self._check_node()
            issues += self._check_git()
            issues += self._check_docker()
            issues += self._check_java()
            issues += self._check_vscode()
            
        if hasattr(self, "resolved_types") and self.resolved_types:
            issues = [x for x in issues if x.get("type") not in self.resolved_types and x.get("recipe_hint") not in self.resolved_types]

        self._scan_completed = True
        self.latest_issues = issues
        return issues

    # â”€â”€ Hardware â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        root = "/" if platform.system() != "Windows" else "C:\\"
        try:
            disk = psutil.disk_usage(root)
            free_gb = disk.free / 1024**3
            if free_gb < 5:
                issues.append({
                    "type": "disk",
                    "severity": SEVERITY_HIGH,
                    "title": "Critical: Low Disk Space",
                    "detail": f"Only {free_gb:.1f} GB free on main drive.",
                    "recipe_hint": "clear_temp",
                })
            elif free_gb < 15:
                issues.append({
                    "type": "disk",
                    "severity": SEVERITY_MEDIUM,
                    "title": "Low Disk Space",
                    "detail": f"{free_gb:.1f} GB free on main drive.",
                    "recipe_hint": "clear_temp",
                })
        except Exception:
            pass
        return issues

    def _check_cpu(self) -> list:
        issues = []
        cpu = psutil.cpu_percent(interval=0.5)
        if cpu > 90:
            issues.append({
                "type": "cpu",
                "severity": SEVERITY_HIGH,
                "title": "CPU Overloaded",
                "detail": f"CPU usage at {cpu}%. Check for runaway processes.",
                "recipe_hint": None,
            })
        return issues

    # â”€â”€ OS-Aware Repository Scanning â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _check_repositories(self) -> list:
        issues = []
        sys_name = platform.system()
        
        if sys_name == "Linux":
            # OS aware: check Debian/Ubuntu source lists
            sources_path = Path("/etc/apt/sources.list")
            sources_dir = Path("/etc/apt/sources.list.d")
            
            # Simple check for locks or configuration issues
            try:
                # Run apt-get check to detect lock-frontend or package manager corruptions
                res = _safe_run(["apt-get", "check"], capture_output=True, text=True, timeout=5)
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
                
            # Verify expired GPG signing keys or unreachable mirrors
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
            # Check winget source list integrity
            if shutil.which("winget"):
                try:
                    res = _safe_run(["winget", "source", "list"], capture_output=True, text=True, timeout=6)
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
                    res = _safe_run(["brew", "doctor"], capture_output=True, text=True, timeout=10)
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
                # Check for updates with a simulated dry-run
                res = _safe_run(["apt-get", "-s", "upgrade"], capture_output=True, text=True, timeout=5)
                # Count lines with packages
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

    # â”€â”€ Windows Update & Platform Checks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _check_windows_update(self) -> list:
        issues = []
        if platform.system() != "Windows":
            return issues
        try:
            res = _safe_run(["powershell", "-Command", "Get-Service wuauserv | Select-Object -ExpandProperty Status"], capture_output=True, text=True, timeout=5)
            status = res.stdout.strip()
            if "Running" not in status:
                issues.append({
                    "type": "service_wuauserv",
                    "severity": SEVERITY_MEDIUM,
                    "title": "Windows Update Agent Stopped",
                    "detail": "The Windows Update service (wuauserv) is inactive. Updates cannot be retrieved.",
                    "recipe_hint": "powershell -Command \"Start-Service wuauserv\""
                })
        except Exception:
            pass
        return issues

    def _check_windows_drivers(self) -> list:
        issues = []
        if platform.system() != "Windows":
            return issues
        try:
            res = _safe_run(["powershell", "-Command", "Get-PnpDevice -Status Error | Select-Object -ExpandProperty FriendlyName"], capture_output=True, text=True, timeout=6)
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

    # â”€â”€ Developer Tools â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _check_python(self) -> list:
        issues = []
        py = shutil.which("python") or shutil.which("python3")
        if not py:
            issues.append({
                "type": "python_path",
                "severity": SEVERITY_MEDIUM,
                "title": "Python Not Found in PATH",
                "detail": "The `python` command is not accessible. PATH may be misconfigured.",
                "recipe_hint": "Python PATH missing",
            })
        return issues

    def _check_node(self) -> list:
        return []

    def _check_git(self) -> list:
        return []

    def _check_docker(self) -> list:
        issues = []
        if not shutil.which("docker"):
            return []
        else:
            try:
                result = _safe_run(
                    ["docker", "info"],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode != 0:
                    issues.append({
                        "type": "docker_stopped",
                        "severity": SEVERITY_MEDIUM,
                        "title": "Docker Daemon Not Running",
                        "detail": "Docker is installed but the daemon is not running.",
                        "recipe_hint": "Docker service stopped",
                    })
            except Exception:
                pass
        return issues

    def _check_java(self) -> list:
        return []

    def _check_vscode(self) -> list:
        return []

    def _check_linux_services(self) -> list:
        issues = []
        # Query failed systemd services
        try:
            res = _safe_run(["systemctl", "--failed", "--type=service", "--quiet"], capture_output=True, text=True, timeout=5)
            # Or run list-units
            res_list = _safe_run(["systemctl", "list-units", "--state=failed", "--type=service", "--no-legend"], capture_output=True, text=True, timeout=5)
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
                result = _safe_run(
                    ["systemctl", "is-active", svc],
                    capture_output=True,
                    timeout=5,
                )
                status = result.stdout.decode().strip()
                if status not in ("active",):
                    # Check if already added in failed units
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
            gpu_res = _safe_run(lspci_cmd, shell=True, capture_output=True, text=True)
            has_nvidia = "nvidia" in gpu_res.stdout.lower() or "geforce" in gpu_res.stdout.lower()
            
            lsmod_res = _safe_run("lsmod | grep nouveau", shell=True, capture_output=True, text=True)
            using_nouveau = "nouveau" in lsmod_res.stdout.lower()
            
            nvidia_loaded = False
            try:
                nvidia_res = _safe_run("lsmod | grep nvidia", shell=True, capture_output=True, text=True)
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

