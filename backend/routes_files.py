import os
import time
import platform
import shutil
from pathlib import Path
from typing import Optional, Any
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
import psutil

from app_context import engine
from logger import log_action

router = APIRouter()


class WriteFileRequest(BaseModel):
    path: str
    content: str


class CreateFileRequest(BaseModel):
    path: str
    name: str
    content: str = ""


class StopProcessRequest(BaseModel):
    pid: int
    pids: list[int] = []


class BrowserTabsRequest(BaseModel):
    pids: list[int]
    name: str = ""
    preview: bool = False


CRITICAL_PROCESS_NAMES = {
    "systemd", "init", "gnome-shell", "gdm", "gdm3", "xorg", "xwayland",
    "wayland", "dbus-daemon", "pipewire", "wireplumber", "pulseaudio",
    "networkmanager", "wpa_supplicant", "snapd", "upowerd", "polkitd",
    "login", "sshd", "bash", "zsh", "fish", "python", "python3",
    "uvicorn", "pc doctor", "codex", "mutter", "gjs",
    "xdg-desktop-portal", "tracker-miner", "gnome-session", "gsd-", "at-spi",
    "system", "svchost", "explorer", "csrss", "smss", "wininit", "services",
    "lsass", "fontdrvhost", "dwm", "taskhostw", "ctfmon", "spoolsv", "conhost",
    "runtimebroker", "sihost", "taskmgr", "securityhealthservice", "searchhost"
}

BROWSER_PROCESS_NAMES = {"brave", "brave-browser", "brave-browser-stable", "chrome", "chromium", "chromium-browser"}


def _gb(num_bytes: int) -> float:
    return round(num_bytes / 1024**3, 2)


def _folder_size(path: Path, max_entries: int = 1200) -> int:
    total = 0
    seen = 0
    stack = [path]
    while stack and seen < max_entries:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    seen += 1
                    if seen >= max_entries:
                        break
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _safe_list_path(raw_path: Optional[str]) -> Path:
    if not raw_path:
        return Path.home()
    try:
        path = Path(raw_path).expanduser().resolve()
    except OSError:
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found.")
    return path


def _is_home_path(path: Path) -> bool:
    try:
        path.resolve().relative_to(Path.home().resolve())
        return True
    except ValueError:
        return False


def _safe_write_path(raw_path: str, must_exist: bool = False) -> Path:
    import re
    try:
        path = Path(raw_path).expanduser().resolve()
    except OSError:
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not _is_home_path(path):
        raise HTTPException(status_code=403, detail="Only files inside your home folder can be modified.")
        
    # Block writing to system/shell configurations in the home directory
    blocked_patterns = [
        r"\.bashrc$",
        r"\.bash_profile$",
        r"\.profile$",
        r"\.bash_login$",
        r"\.bash_logout$",
        r"\.zshrc$",
        r"\.zprofile$",
        r"\.zshenv$",
        r"\.zlogin$",
        r"\.zlogout$",
        r"\.ssh/",
        r"\.ssh$",
        r"\.pam_environment$",
        r"\.config/autostart/",
        r"\.local/share/autostart/",
        r"appdata/roaming/microsoft/windows/start menu/programs/startup",
    ]
    path_str = str(path).replace("\\", "/").lower()
    for pattern in blocked_patterns:
        if re.search(pattern, path_str):
            raise HTTPException(status_code=403, detail="Modification of shell configurations or security settings is blocked.")

    if must_exist and not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return path


def _safe_child_path(parent_raw: str, name: str) -> Path:
    if not name.strip() or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Use a simple file or folder name.")
    parent = _safe_write_path(parent_raw, must_exist=True)
    if not parent.is_dir():
        raise HTTPException(status_code=400, detail="Parent path is not a folder.")
    child = (parent / name.strip()).resolve()
    if not _is_home_path(child):
        raise HTTPException(status_code=403, detail="Only files inside your home folder can be modified.")
    return child


def _is_editable_text_file(path: Path) -> bool:
    editable_exts = {
        ".txt", ".md", ".json", ".js", ".css", ".html", ".py", ".rs", ".toml",
        ".yaml", ".yml", ".ini", ".conf", ".log", ".sh", ".ps1",
    }
    return path.is_file() and path.suffix.lower() in editable_exts


def _folder_entry(path: Path) -> dict:
    try:
        stat = path.stat()
        is_dir = path.is_dir()
        size = 0 if is_dir else stat.st_size
        writable = _is_home_path(path)
        return {
            "name": path.name or str(path),
            "path": str(path),
            "type": "folder" if is_dir else "file",
            "size_gb": _gb(size),
            "size_bytes": size,
            "modified": stat.st_mtime,
            "read_only": not writable,
            "writable": writable,
            "editable": writable and _is_editable_text_file(path),
        }
    except OSError:
        return {
            "name": path.name or str(path),
            "path": str(path),
            "type": "unknown",
            "size_gb": 0,
            "size_bytes": 0,
            "modified": 0,
            "read_only": True,
            "writable": False,
            "editable": False,
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


def _process_dashboard_status(proc: psutil.Process, current_uid: Optional[int]) -> Optional[dict]:
    try:
        info = proc.info
        name = (info.get("name") or "").lower()
        pid = int(info.get("pid") or 0)
        if pid <= 1 or pid == os.getpid():
            return None

        if current_uid is not None:
            try:
                uids = info.get("uids") or (proc.uids() if hasattr(proc, "uids") else None)
                if uids is not None and uids.real != current_uid:
                    return None
            except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
                pass

        critical = any(blocked in name for blocked in CRITICAL_PROCESS_NAMES)
        category_label = "Necessary Windows process" if platform.system() == "Windows" else "Necessary Linux app"
        return {
            "stoppable": not critical,
            "category": category_label if critical else "Application",
        }
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return None


def _is_browser_name(name: str) -> bool:
    # Always return False so all browsers are treated as normal user apps
    # with a standard "Stop" button in the dashboard, enabling complete termination.
    return False


def _cmdline(proc: psutil.Process) -> str:
    try:
        return " ".join(proc.cmdline())
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return ""


def _is_current_pc_doctor_browser_process(cmdline: str) -> bool:
    lowered = cmdline.lower()
    ports = [8765, 8080, 8000, 3000, 9000, 7000, 5000]
    for p in ports:
        if f"localhost:{p}" in lowered or f"127.0.0.1:{p}" in lowered or f":{p} " in lowered or f":{p}]" in lowered:
            return True
    if "pc doctor" in lowered or "frontend" in lowered or "index.html" in lowered:
        return True
    return False


def _is_browser_renderer(cmdline: str) -> bool:
    lowered = cmdline.lower()
    if "--type=renderer" in lowered:
        return True
    if "-contentproc" in lowered or "web content" in lowered or "plugin-container" in lowered:
        return True
    if "content-process" in lowered or "--type=content" in lowered:
        return True
    return False


def _system_disk_path() -> str:
    if platform.system() == "Windows":
        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


_dashboard_resources_cache = {"timestamp": 0, "payload": None}
_cached_dashboard_roots = None
_PROC_CPU_HISTORY: dict[int, tuple[float, float]] = {}

def _get_cached_roots():
    global _cached_dashboard_roots
    if _cached_dashboard_roots is not None:
        return _cached_dashboard_roots
    home = Path.home()
    roots = [
        {"label": "Home", "path": str(home), "read_only": True},
    ]
    for folder_name in ["Desktop", "Downloads", "Documents", "Pictures", "Music", "Videos"]:
        p = home / folder_name
        try:
            if p.exists() and p.is_dir():
                roots.append({"label": folder_name, "path": str(p), "read_only": True})
        except Exception:
            pass
    roots.append({"label": "OS Files", "path": _system_disk_path(), "read_only": True})
    _cached_dashboard_roots = roots
    return roots


@router.get("/api/dashboard/resources")
def dashboard_resources():
    """Return dashboard-only disk folders and stoppable user apps at Task Manager refresh speed."""
    global _PROC_CPU_HISTORY
    now = time.time()
    if _dashboard_resources_cache["payload"] is not None and (now - _dashboard_resources_cache["timestamp"]) < 1.2:
        return _dashboard_resources_cache["payload"]

    roots = _get_cached_roots()
    current_uid = os.getuid() if hasattr(os, "getuid") else None
    app_groups = {}

    proc_attrs = ["pid", "name", "memory_info", "cpu_times"]
    if platform.system() != "Windows":
        proc_attrs.append("uids")

    num_cores = psutil.cpu_count() or 1
    total_mem = psutil.virtual_memory().total or 1
    new_cpu_history = {}

    for proc in psutil.process_iter(proc_attrs):
        try:
            info = proc.info
            name = info.get("name") or ""
            if not name:
                continue
            status = _process_dashboard_status(proc, current_uid)
            if status is None:
                continue

            pid = info["pid"]
            cpu_times = info.get("cpu_times")
            cpu_pct = 0.0
            if cpu_times:
                total_cpu_time = cpu_times.user + cpu_times.system
                new_cpu_history[pid] = (total_cpu_time, now)
                if pid in _PROC_CPU_HISTORY:
                    prev_cpu_time, prev_time = _PROC_CPU_HISTORY[pid]
                    dt = now - prev_time
                    if dt > 0.05:
                        cpu_pct = max(0.0, ((total_cpu_time - prev_cpu_time) / dt) * 100.0 / num_cores)

            mem_info = info.get("memory_info")
            rss_bytes = mem_info.rss if mem_info else 0

            if name not in app_groups:
                app_groups[name] = {
                    "name": name,
                    "command": name,
                    "cpu_percent": 0.0,
                    "memory_percent": 0.0,
                    "memory_mb": 0.0,
                    "process_count": 0,
                    "pids": [],
                    "stoppable": status["stoppable"],
                    "category": status["category"],
                    "browser_control": False,
                }
            group = app_groups[name]
            group["pids"].append(pid)
            group["process_count"] += 1
            group["cpu_percent"] += cpu_pct
            group["memory_mb"] += rss_bytes / (1024 * 1024)
            group["memory_percent"] += (rss_bytes / total_mem) * 100.0
            group["stoppable"] = group["stoppable"] and status["stoppable"]
            if not group["stoppable"]:
                group["category"] = "Necessary Windows process" if platform.system() == "Windows" else "Necessary Linux app"
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue

    _PROC_CPU_HISTORY = new_cpu_history

    apps = list(app_groups.values())
    for app in apps:
        app["cpu_percent"] = round(app["cpu_percent"], 1)
        app["memory_percent"] = round(app["memory_percent"], 1)
        app["memory_mb"] = round(app["memory_mb"], 1)

    normal_apps = [app for app in apps if app["stoppable"]]
    necessary_apps = [app for app in apps if not app["stoppable"]]
    normal_apps.sort(key=lambda p: (-(p["cpu_percent"]), -(p["memory_mb"])))
    necessary_apps.sort(key=lambda p: (-(p["cpu_percent"]), -(p["memory_mb"])))

    sorted_apps = normal_apps + necessary_apps

    payload = {
        "ok": True,
        "roots": roots,
        "apps": sorted_apps,
        "total_apps": len(sorted_apps),
        "stoppable_apps_count": len(normal_apps),
        "necessary_apps_count": len(necessary_apps),
    }

    _dashboard_resources_cache["timestamp"] = now
    _dashboard_resources_cache["payload"] = payload
    return payload


@router.get("/api/files/list")
async def list_files(path: Optional[str] = None, limit: int = 1000):
    """Read-only file-manager style folder listing."""
    folder = _safe_list_path(path)
    home = Path.home().resolve()
    entries = []
    try:
        for child in folder.iterdir():
            if child.name.startswith("."):
                continue
            entries.append(_folder_entry(child))
    except OSError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    entries.sort(key=lambda item: (item["type"] != "folder", item["name"].lower()))
    parent = folder.parent if folder.parent != folder else None
    return {
        "ok": True,
        "path": str(folder),
        "parent": str(parent) if parent else None,
        "read_only": not _is_home_path(folder),
        "writable": _is_home_path(folder),
        "is_os_path": not str(folder).startswith(str(home)),
        "entries": entries[:limit],
    }


class DeleteFileRequest(BaseModel):
    path: str


@router.post("/api/files/delete")
async def delete_file(req: DeleteFileRequest):
    """Delete a file or folder inside the user's home folder safely."""
    file_path = _safe_write_path(req.path, must_exist=True)
    
    # Extra protection: do not allow deleting key root home directories
    home = Path.home().resolve()
    if file_path == home or file_path in [home / "Desktop", home / "Downloads", home / "Documents", home / "Pictures", home / "Videos", home / "Music"]:
        raise HTTPException(status_code=403, detail="Deleting main home directories is blocked for system safety.")
        
    try:
        if file_path.is_dir():
            shutil.rmtree(file_path)
            log_action("EXECUTE", f"delete folder {file_path}", "Deleted user folder", friendly_summary=f"Deleted folder {file_path.name}")
        else:
            file_path.unlink()
            log_action("EXECUTE", f"delete file {file_path}", "Deleted user file", friendly_summary=f"Deleted file {file_path.name}")
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/files/read")
async def read_file(path: str):
    """Read a home-folder text file for editing."""
    file_path = _safe_write_path(path, must_exist=True)
    if not _is_editable_text_file(file_path):
        raise HTTPException(status_code=400, detail="Only small text/code files can be edited.")
    if file_path.stat().st_size > 1024 * 1024:
        raise HTTPException(status_code=400, detail="File is too large to edit here.")
    return {
        "ok": True,
        "path": str(file_path),
        "content": file_path.read_text(encoding="utf-8", errors="replace"),
    }


@router.post("/api/files/write")
async def write_file(req: WriteFileRequest):
    """Write a home-folder text file. OS/installed app paths are denied."""
    file_path = _safe_write_path(req.path, must_exist=False)
    if not _is_editable_text_file(file_path):
        raise HTTPException(status_code=400, detail="Only text/code files can be edited.")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(req.content, encoding="utf-8")
    log_action("EXECUTE", f"write file {file_path}", "Edited user file", friendly_summary=f"Saved {file_path.name}")
    return {"ok": True, "path": str(file_path)}


@router.post("/api/files/create_file")
async def create_file(req: CreateFileRequest):
    """Create a file inside the user's home folder."""
    file_path = _safe_child_path(req.path, req.name)
    if file_path.exists():
        raise HTTPException(status_code=409, detail="File already exists.")
    file_path.write_text(req.content, encoding="utf-8")
    log_action("EXECUTE", f"create file {file_path}", "Created user file", friendly_summary=f"Created {file_path.name}")
    return {"ok": True, "path": str(file_path)}


@router.post("/api/files/create_folder")
async def create_folder(req: CreateFileRequest):
    """Create a folder inside the user's home folder."""
    folder_path = _safe_child_path(req.path, req.name)
    if folder_path.exists():
        raise HTTPException(status_code=409, detail="Folder already exists.")
    folder_path.mkdir(parents=False)
    log_action("EXECUTE", f"create folder {folder_path}", "Created user folder", friendly_summary=f"Created {folder_path.name}")
    return {"ok": True, "path": str(folder_path)}


def _clear_browser_cache_and_restore(browser_type: str):
    import platform
    import shutil
    import json
    import os
    from pathlib import Path
    
    system = platform.system()
    home = Path.home()
    
    cache_paths = []
    user_data_paths = []
    
    if system == "Linux":
        if browser_type == "chrome":
            cache_paths = [home / ".cache" / "google-chrome"]
            user_data_paths = [home / ".config" / "google-chrome"]
        elif browser_type == "chromium":
            cache_paths = [home / ".cache" / "chromium"]
            user_data_paths = [home / ".config" / "chromium"]
        elif browser_type == "brave":
            cache_paths = [home / ".cache" / "BraveSoftware", home / ".cache" / "brave"]
            user_data_paths = [home / ".config" / "BraveSoftware" / "Brave-Browser"]
        elif browser_type == "firefox":
            cache_paths = [home / ".cache" / "mozilla" / "firefox"]
            user_data_paths = [home / ".mozilla" / "firefox"]
        elif browser_type == "edge":
            cache_paths = [home / ".cache" / "microsoft-edge", home / ".cache" / "microsoft-edge-dev", home / ".cache" / "microsoft-edge-beta"]
            user_data_paths = [home / ".config" / "microsoft-edge", home / ".config" / "microsoft-edge-dev", home / ".config" / "microsoft-edge-beta"]
        elif browser_type == "opera":
            cache_paths = [home / ".cache" / "opera"]
            user_data_paths = [home / ".config" / "opera"]
        elif browser_type == "vivaldi":
            cache_paths = [home / ".cache" / "vivaldi"]
            user_data_paths = [home / ".config" / "vivaldi"]
            
    elif system == "Windows":
        local_appdata = Path(os.environ.get("LOCALAPPDATA", "")) if os.environ.get("LOCALAPPDATA") else None
        appdata = Path(os.environ.get("APPDATA", "")) if os.environ.get("APPDATA") else None
        
        if browser_type == "chrome" and local_appdata:
            cache_paths = [local_appdata / "Google" / "Chrome" / "User Data" / "Default" / "Cache"]
            user_data_paths = [local_appdata / "Google" / "Chrome" / "User Data"]
        elif browser_type == "chromium" and local_appdata:
            cache_paths = [local_appdata / "Chromium" / "User Data" / "Default" / "Cache"]
            user_data_paths = [local_appdata / "Chromium" / "User Data"]
        elif browser_type == "brave" and local_appdata:
            cache_paths = [local_appdata / "BraveSoftware" / "Brave-Browser" / "User Data" / "Default" / "Cache"]
            user_data_paths = [local_appdata / "BraveSoftware" / "Brave-Browser" / "User Data"]
        elif browser_type == "firefox" and local_appdata and appdata:
            cache_paths = [local_appdata / "Mozilla" / "Firefox" / "Profiles"]
            user_data_paths = [appdata / "Mozilla" / "Firefox" / "Profiles"]
        elif browser_type == "edge" and local_appdata:
            cache_paths = [local_appdata / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache"]
            user_data_paths = [local_appdata / "Microsoft" / "Edge" / "User Data"]
        elif browser_type == "opera" and local_appdata and appdata:
            cache_paths = [local_appdata / "Opera Software" / "Opera Stable" / "Cache"]
            user_data_paths = [appdata / "Opera Software" / "Opera Stable", local_appdata / "Opera Software" / "Opera Stable"]
        elif browser_type == "vivaldi" and local_appdata:
            cache_paths = [local_appdata / "Vivaldi" / "User Data" / "Default" / "Cache"]
            user_data_paths = [local_appdata / "Vivaldi" / "User Data"]
            
    elif system == "Darwin":
        if browser_type == "chrome":
            cache_paths = [home / "Library" / "Caches" / "Google" / "Chrome"]
            user_data_paths = [home / "Library" / "Application Support" / "Google" / "Chrome"]
        elif browser_type == "chromium":
            cache_paths = [home / "Library" / "Caches" / "Chromium"]
            user_data_paths = [home / "Library" / "Application Support" / "Chromium"]
        elif browser_type == "brave":
            cache_paths = [home / "Library" / "Caches" / "BraveSoftware"]
            user_data_paths = [home / "Library" / "Application Support" / "BraveSoftware" / "Brave-Browser"]
        elif browser_type == "firefox":
            cache_paths = [home / "Library" / "Caches" / "Firefox"]
            user_data_paths = [home / "Library" / "Application Support" / "Firefox" / "Profiles"]
        elif browser_type == "edge":
            cache_paths = [home / "Library" / "Caches" / "Microsoft Edge"]
            user_data_paths = [home / "Library" / "Application Support" / "Microsoft Edge"]
        elif browser_type == "opera":
            cache_paths = [home / "Library" / "Caches" / "Opera Software"]
            user_data_paths = [home / "Library" / "Application Support" / "com.operasoftware.Opera"]
        elif browser_type == "vivaldi":
            cache_paths = [home / "Library" / "Caches" / "Vivaldi"]
            user_data_paths = [home / "Library" / "Application Support" / "Vivaldi"]

    # Clear caches
    for cp in cache_paths:
        if cp.exists():
            try:
                shutil.rmtree(cp)
            except Exception:
                pass

    # Clear session restore data / restore pages banners
    if browser_type == "firefox":
        # Delete sessionstore files and backups
        for udp in user_data_paths:
            if udp.exists():
                for file_path in list(udp.glob("**/sessionstore*")):
                    try:
                        if file_path.is_file():
                            file_path.unlink()
                        elif file_path.is_dir():
                            shutil.rmtree(file_path)
                    except Exception:
                        pass
    else:
        # Chromium-based: find all Preferences files under user data path
        for udp in user_data_paths:
            if udp.exists():
                for pref_path in list(udp.glob("**/Preferences")):
                    if pref_path.is_file():
                        try:
                            # Load JSON, modify, and save
                            txt = pref_path.read_text(encoding="utf-8", errors="replace")
                            data = json.loads(txt)
                            
                            # Clean exit settings
                            if "profile" not in data or not isinstance(data["profile"], dict):
                                data["profile"] = {}
                            
                            data["profile"]["exit_type"] = "Normal"
                            data["profile"]["exited_cleanly"] = True
                            
                            # Flat keys just in case
                            data["exit_type"] = "Normal"
                            data["exited_cleanly"] = True
                            
                            pref_path.write_text(json.dumps(data), encoding="utf-8")
                        except Exception:
                            pass


@router.post("/api/process/stop")
async def stop_process(req: StopProcessRequest):
    """Terminate a non-critical process owned by the current user."""
    current_uid = os.getuid() if hasattr(os, "getuid") else None
    target_pids = req.pids or [req.pid]
    stopped = []
    blocked = []

    for pid in target_pids:
        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            continue
        if not _is_noncritical_user_process(proc, current_uid):
            blocked.append(pid)
            continue
        name = proc.name()
        proc.terminate()
        stopped.append((pid, name, proc))

    for pid, name, proc in stopped:
        try:
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                blocked.append(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Clear cache and restore state for all stopped browsers
    stopped_browsers = set()
    for _, name, _ in stopped:
        lowered = name.lower()
        if "chrome" in lowered:
            stopped_browsers.add("chrome")
        elif "chromium" in lowered:
            stopped_browsers.add("chromium")
        elif "brave" in lowered:
            stopped_browsers.add("brave")
        elif "firefox" in lowered:
            stopped_browsers.add("firefox")
        elif "msedge" in lowered or "microsoft-edge" in lowered:
            stopped_browsers.add("edge")
        elif "opera" in lowered:
            stopped_browsers.add("opera")
        elif "vivaldi" in lowered:
            stopped_browsers.add("vivaldi")

    for browser in stopped_browsers:
        try:
            _clear_browser_cache_and_restore(browser)
        except Exception:
            pass

    if not stopped:
        raise HTTPException(status_code=403, detail="No non-critical user processes were stopped.")

    names = sorted({name for _, name, _ in stopped})
    summary = ", ".join(names[:3])
    if blocked:
        summary += f" ({len(blocked)} process(es) refused or still running)"

    log_action(
        "EXECUTE",
        f"terminate pids {','.join(str(pid) for pid, _, _ in stopped)}",
        f"Stopped non-critical app group: {summary}",
        friendly_summary=f"Stopped {summary}",
    )
    return {"ok": True, "message": f"Stopped {summary}", "pids": [pid for pid, _, _ in stopped]}


@router.post("/api/ram/kill")
async def ram_kill(req: StopProcessRequest):
    """Compatibility wrapper for process stopping from Dashboard."""
    result = await stop_process(req)
    return result


@router.post("/api/browser/close_other_tabs")
async def close_other_browser_tabs(req: BrowserTabsRequest):
    """Best-effort close for browser tab renderer processes while keeping PC Doctor open."""
    current_uid = os.getuid() if hasattr(os, "getuid") else None
    renderers: list[psutil.Process] = []

    # Build a fast lookup of the provided app PIDs so we can detect child/content procs
    app_pids = set(int(p) for p in (req.pids or []))

    proc_attrs = ["pid", "ppid", "name", "cmdline"]
    if platform.system() != "Windows":
        proc_attrs.append("uids")

    for proc in psutil.process_iter(proc_attrs):
        try:
            info = proc.info
            pid = int(info.get("pid") or 0)
            ppid = int(info.get("ppid") or 0)
            name = (info.get("name") or "").lower()
            cmdline = " ".join(info.get("cmdline") or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

        # Respect UID boundaries
        if current_uid is not None:
            try:
                uids = info.get("uids") or (proc.uids() if hasattr(proc, "uids") else None)
                if uids is not None and uids.real != current_uid:
                    continue
            except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
                continue

        # Skip non-browser processes
        if not (_is_browser_name(name) or _is_browser_renderer(cmdline)):
            continue

        # Never target the PC Doctor tab/process
        if _is_current_pc_doctor_browser_process(cmdline):
            continue

        # Only include true renderer/content processes
        is_renderer = _is_browser_renderer(cmdline)
        if not is_renderer:
            continue

        include = False
        if not app_pids:
            include = True
        else:
            if pid in app_pids or ppid in app_pids:
                include = True
            else:
                try:
                    parent = proc.parent()
                    while parent and parent.pid and parent.pid != 1:
                        if parent.pid in app_pids:
                            include = True
                            break
                        parent = parent.parent()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    include = False

        if include:
            renderers.append(proc)

    try:
        found_info = []
        for p in renderers:
            try:
                found_info.append(f"{p.pid}:{_cmdline(p)[:140]}")
            except Exception:
                found_info.append(str(p.pid))
        log_action("DEBUG", "close_other_tabs candidates", ", ".join(found_info))
    except Exception:
        pass

    renderers.sort(key=lambda proc: proc.pid)
    targets = renderers[1:] if len(renderers) > 1 else []

    candidates_info = []
    for p in renderers:
        try:
            candidates_info.append({"pid": p.pid, "cmd": _cmdline(p)[:200]})
        except Exception:
            candidates_info.append({"pid": getattr(p, "pid", None), "cmd": ""})
    targets_info = []
    for p in targets:
        try:
            targets_info.append({"pid": p.pid, "cmd": _cmdline(p)[:200]})
        except Exception:
            targets_info.append({"pid": getattr(p, "pid", None), "cmd": ""})

    if getattr(req, "preview", False):
        return {
            "ok": True,
            "message": "Preview: renderer detection only.",
            "candidates": candidates_info,
            "targets": targets_info,
        }

    closed = []
    for proc in targets:
        try:
            pid = proc.pid
            proc.terminate()
            closed.append(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    for proc in targets:
        try:
            proc.wait(timeout=3)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            pass

    summary = f"closed {len(closed)} other browser tab renderer(s)"
    log_action("EXECUTE", f"close other tabs: {', '.join(str(p) for p in closed)}", summary)
    return {"ok": True, "message": summary, "closed": closed}
