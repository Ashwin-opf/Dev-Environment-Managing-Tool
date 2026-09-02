"""
Cross-platform developer tool detection.
Uses PATH, common install paths, snap/flatpak, desktop entries, and running processes.
"""
from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Iterable, Optional

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def _home() -> Path:
    return Path.home()


def _exists(path: Optional[str | Path]) -> bool:
    if not path:
        return False
    try:
        return Path(path).exists()
    except Exception:
        return False


def _is_mock_installed_in_dev_mode(tool_name: str) -> bool:
    from feature_flags import ENABLE_DEV_MODE
    if not ENABLE_DEV_MODE:
        return False
    import sqlite3
    from self_healing import DB_PATH
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM self_healing_attempts
            WHERE result = 'Healing Successful' AND (
                LOWER(attempted_fix) LIKE ? OR LOWER(error_source) LIKE ? OR LOWER(error_message) LIKE ?
            )
        """, (f"%{tool_name.lower()}%", f"%{tool_name.lower()}%", f"%{tool_name.lower()}%"))
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


def _which(*names: str) -> bool:
    return any(shutil.which(name) for name in names)


def _any_exists(paths: Iterable[str | Path]) -> bool:
    return any(_exists(path) for path in paths)


def _flatpak_installed(app_id: str) -> bool:
    # Check common flatpak directory paths instead of running 'flatpak info'
    paths = [
        Path(f"/var/lib/flatpak/app/{app_id}"),
        Path(f"/var/lib/flatpak/exports/share/applications/{app_id}.desktop"),
        _home() / f".local/share/flatpak/app/{app_id}",
        _home() / f".local/share/flatpak/exports/share/applications/{app_id}.desktop",
    ]
    return any(p.exists() for p in paths)


def _snap_installed(snap_name: str) -> bool:
    # Check common snap directories directly instead of spawning the slow 'snap list' command
    paths = [
        Path(f"/snap/{snap_name}"),
        Path(f"/var/lib/snapd/snap/{snap_name}"),
        Path(f"/var/lib/snapd/desktop/applications/{snap_name}.desktop")
    ]
    return any(p.exists() for p in paths)


def _desktop_installed(filenames: Iterable[str]) -> bool:
    dirs = [
        Path("/usr/share/applications"),
        Path("/var/lib/snapd/desktop/applications"),
        Path("/var/lib/flatpak/exports/share/applications"),
        _home() / ".local/share/applications",
        _home() / ".local/share/flatpak/exports/share/applications",
    ]
    for directory in dirs:
        for filename in filenames:
            if (directory / filename).is_file():
                return True
    return False


def _process_markers(markers: Iterable[str], exact_names: Optional[set[str]] = None) -> bool:
    return False


def detect_tool(
    binaries: Iterable[str] = (),
    paths: Iterable[str | Path] = (),
    flatpak_ids: Iterable[str] = (),
    snap_names: Iterable[str] = (),
    desktop_files: Iterable[str] = (),
    process_markers: Iterable[str] = (),
    exact_process_names: Iterable[str] = (),
) -> bool:
    for name in binaries:
        if shutil.which(name):
            return True

    if _any_exists(paths):
        return True
    if any(_flatpak_installed(app_id) for app_id in flatpak_ids):
        return True
    if any(_snap_installed(snap_name) for snap_name in snap_names):
        return True
    if _desktop_installed(desktop_files):
        return True
    return False


def python_installed() -> bool:
    if _is_mock_installed_in_dev_mode("python"):
        return True
    return detect_tool(
        binaries=("python3", "python", "py"),
        paths=(
            "/usr/bin/python3",
            "/usr/local/bin/python3",
            _home() / ".pyenv/shims/python3",
            _home() / ".local/bin/python3",
        ),
        process_markers=("/usr/bin/python", "python3"),
        exact_process_names=("python", "python3"),
    )


def pip_installed() -> bool:
    if _is_mock_installed_in_dev_mode("pip"):
        return True
    if detect_tool(binaries=("pip3", "pip"), paths=(_home() / ".local/bin/pip3",)):
        return True
    # Fast check: see if python3 exists and it has a pip module directory in site-packages
    # instead of spawning a python3 subprocess.
    for p in Path("/usr/lib").glob("python3*/dist-packages/pip"):
        if p.is_dir():
            return True
    for p in Path("/usr/local/lib").glob("python3*/site-packages/pip"):
        if p.is_dir():
            return True
    return False


def node_installed() -> bool:
    if _is_mock_installed_in_dev_mode("node"):
        return True
    return detect_tool(
        binaries=("node", "nodejs"),
        paths=(
            "/usr/bin/node",
            "/usr/local/bin/node",
            _home() / ".nvm/current/bin/node",
        ),
        process_markers=("/usr/bin/node", ".nvm/versions/node/"),
        exact_process_names=("node",),
    )


def npm_installed() -> bool:
    if _is_mock_installed_in_dev_mode("npm"):
        return True
    return detect_tool(
        binaries=("npm", "npm.cmd"),
        paths=(
            "/usr/bin/npm",
            _home() / ".nvm/current/bin/npm",
            _home() / ".local/bin/npm",
        ),
        process_markers=("npm-cli.js", "/usr/bin/npm"),
        exact_process_names=("npm",),
    )


def _program_files() -> list[Path]:
    paths = []
    if platform.system() == "Windows":
        for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            val = os.environ.get(env_var)
            if val:
                paths.append(Path(val))
    elif platform.system() == "Darwin":
        paths.extend([Path("/Applications"), Path("/opt/homebrew/bin"), Path("/usr/local/bin")])
    return paths


def git_installed() -> bool:
    if _is_mock_installed_in_dev_mode("git"):
        return True
    pf_paths = [pf / "Git/bin/git.exe" for pf in _program_files()]
    return detect_tool(
        binaries=("git", "git.exe"),
        paths=(
            "/usr/bin/git",
            "/usr/local/bin/git",
            "/opt/homebrew/bin/git",
            *pf_paths,
        ),
        process_markers=("/usr/bin/git", "git.exe"),
        exact_process_names=("git", "git.exe"),
    )


def docker_installed() -> bool:
    if _is_mock_installed_in_dev_mode("docker"):
        return True
    pf_paths = [pf / "Docker/Docker/resources/bin/docker.exe" for pf in _program_files()]
    return detect_tool(
        binaries=("docker", "docker.exe"),
        paths=(
            "/usr/bin/docker",
            "/usr/local/bin/docker",
            "/opt/homebrew/bin/docker",
            "/snap/bin/docker",
            *pf_paths,
        ),
        snap_names=("docker",),
        desktop_files=("docker-desktop.desktop",),
        process_markers=("dockerd", "com.docker.backend", "docker desktop"),
    )


def java_installed() -> bool:
    if _is_mock_installed_in_dev_mode("java"):
        return True
    pf_paths = []
    for pf in _program_files():
        pf_paths.extend([pf / "Java", pf / "Eclipse Adoptium"])
    return detect_tool(
        binaries=("java", "javac"),
        paths=(
            "/usr/bin/java",
            "/usr/local/bin/java",
            "/opt/homebrew/bin/java",
            *pf_paths,
        ),
        process_markers=("/usr/bin/java", "java.exe", "jdk"),
        exact_process_names=("java", "java.exe"),
    )


def snap_installed() -> bool:
    return detect_tool(
        binaries=("snap",),
        paths=("/usr/bin/snap", "/snap/bin/snap"),
    )


def android_studio_installed() -> bool:
    pf_paths = [pf / "Android/Android Studio/bin/studio64.exe" for pf in _program_files()]
    return detect_tool(
        binaries=("android-studio", "studio", "studio.sh"),
        paths=(
            "/snap/bin/android-studio",
            "/opt/android-studio/bin/studio.sh",
            "/Applications/Android Studio.app/Contents/MacOS/studio",
            _home() / "android-studio/bin/studio.sh",
            *pf_paths,
        ),
        flatpak_ids=("com.google.AndroidStudio",),
        snap_names=("android-studio",),
        desktop_files=("android-studio.desktop", "jetbrains-android-studio.desktop"),
        process_markers=("android-studio", "studio64.exe", "Android Studio"),
    )


def vscode_installed() -> bool:
    if _is_mock_installed_in_dev_mode("code") or _is_mock_installed_in_dev_mode("vscode"):
        return True
    pf_paths = []
    for pf in _program_files():
        pf_paths.extend([
            pf / "Microsoft VS Code/bin/code.cmd",
            pf / "Microsoft VS Code/Code.exe",
            pf / "Programs/Microsoft VS Code/bin/code.cmd",
        ])
    return detect_tool(
        binaries=("code", "code-oss", "code-insiders", "code.cmd"),
        paths=(
            "/snap/bin/code",
            "/usr/bin/code",
            "/usr/local/bin/code",
            "/opt/homebrew/bin/code",
            "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
            "/var/lib/snapd/snap/bin/code",
            "/var/lib/flatpak/exports/bin/com.visualstudio.code",
            "/var/lib/flatpak/exports/bin/code",
            _home() / ".local/share/flatpak/exports/bin/com.visualstudio.code",
            _home() / ".local/share/flatpak/exports/bin/code",
            "/opt/visual-studio-code/bin/code",
            "/usr/share/code/bin/code",
            *pf_paths,
        ),
        flatpak_ids=("com.visualstudio.code",),
        snap_names=("code",),
        desktop_files=("code.desktop", "visual-studio-code.desktop", "com.visualstudio.code.desktop"),
        process_markers=("com.visualstudio.code", "/visual-studio-code/", "/usr/share/code/", "Code.exe"),
        exact_process_names=("code", "code-oss", "code-insiders"),
    )


def java_home_configured() -> bool:
    if os.environ.get("JAVA_HOME"):
        return True
    for config_name in (".bashrc", ".profile", ".zshrc"):
        config_path = _home() / config_name
        if not config_path.is_file():
            continue
        try:
            if "export JAVA_HOME=" in config_path.read_text():
                return True
        except Exception:
            continue
    return False


def poetry_installed() -> bool:
    if _is_mock_installed_in_dev_mode("poetry"):
        return True
    return detect_tool(
        binaries=("poetry",),
        paths=(
            "/usr/bin/poetry",
            "/usr/local/bin/poetry",
            _home() / ".local/bin/poetry",
            _home() / ".poetry/bin/poetry",
        )
    )


def pnpm_installed() -> bool:
    if _is_mock_installed_in_dev_mode("pnpm"):
        return True
    return detect_tool(
        binaries=("pnpm",),
        paths=(
            "/usr/bin/pnpm",
            "/usr/local/bin/pnpm",
            _home() / ".local/share/pnpm/pnpm",
            _home() / ".local/bin/pnpm",
            _home() / ".nvm/current/bin/pnpm",
        )
    )


def ollama_installed() -> bool:
    if _is_mock_installed_in_dev_mode("ollama"):
        return True
    return detect_tool(
        binaries=("ollama",),
        paths=(
            "/usr/bin/ollama",
            "/usr/local/bin/ollama",
            "/usr/share/ollama",
        )
    )

