"""
Cross-platform developer tool detection.
Uses PATH, winreg (Windows registry), common install paths,
snap/flatpak, desktop entries, and running processes.
Priority: shutil.which → known paths → winreg → flatpak/snap/desktop
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
    paths = [
        Path(f"/var/lib/flatpak/app/{app_id}"),
        Path(f"/var/lib/flatpak/exports/share/applications/{app_id}.desktop"),
        _home() / f".local/share/flatpak/app/{app_id}",
        _home() / f".local/share/flatpak/exports/share/applications/{app_id}.desktop",
    ]
    return any(p.exists() for p in paths)


def _snap_installed(snap_name: str) -> bool:
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


# ─── Windows-specific helpers ────────────────────────────────────────────────

def _win_env(var: str) -> Path | None:
    val = os.environ.get(var)
    return Path(val) if val else None


def _win_local() -> Path | None:
    return _win_env("LOCALAPPDATA")


def _win_pf() -> list[Path]:
    dirs: list[Path] = []
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432"):
        p = _win_env(var)
        if p and p not in dirs:
            dirs.append(p)
    return dirs


def _win_user_pf() -> Path | None:
    local = _win_local()
    return (local / "Programs") if local else None


def _win_glob(pattern: str) -> bool:
    import glob as _glob
    try:
        return len(_glob.glob(pattern, recursive=True)) > 0
    except Exception:
        return False


def _win_reg_check(*sub_keys: str) -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import winreg
        for sub_key in sub_keys:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, sub_key):
                        return True
                except FileNotFoundError:
                    continue
    except Exception:
        pass
    return False


def detect_tool(
    binaries: Iterable[str] = (),
    paths: Iterable[str | Path] = (),
    flatpak_ids: Iterable[str] = (),
    snap_names: Iterable[str] = (),
    desktop_files: Iterable[str] = (),
    process_markers: Iterable[str] = (),
    exact_process_names: Iterable[str] = (),
    win_glob_patterns: Iterable[str] = (),
    win_reg_keys: Iterable[str] = (),
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
    if platform.system() == "Windows":
        for pattern in win_glob_patterns:
            if _win_glob(pattern):
                return True
        if win_reg_keys and _win_reg_check(*win_reg_keys):
            return True
    return False


# ─── Individual tool detectors ───────────────────────────────────────────────

def python_installed() -> bool:
    if _is_mock_installed_in_dev_mode("python"):
        return True
    local = _win_local()
    win_paths: list[Path] = []
    if local:
        win_paths = list(local.glob("Programs/Python/Python3*/python.exe"))
        win_paths += [local / "Programs/Python/python.exe"]
    return detect_tool(
        binaries=("python3", "python", "py"),
        paths=(
            "/usr/bin/python3",
            "/usr/local/bin/python3",
            _home() / ".pyenv/shims/python3",
            _home() / ".local/bin/python3",
            *win_paths,
        ),
        process_markers=("/usr/bin/python", "python3"),
        exact_process_names=("python", "python3"),
    )


def pip_installed() -> bool:
    if _is_mock_installed_in_dev_mode("pip"):
        return True
    if detect_tool(binaries=("pip3", "pip"), paths=(_home() / ".local/bin/pip3",)):
        return True
    try:
        for p in Path("/usr/lib").glob("python3*/dist-packages/pip"):
            if p.is_dir():
                return True
        for p in Path("/usr/local/lib").glob("python3*/site-packages/pip"):
            if p.is_dir():
                return True
    except Exception:
        pass
    return False


def node_installed() -> bool:
    if _is_mock_installed_in_dev_mode("node"):
        return True
    local = _win_local()
    win_paths: list[Path] = []
    if local:
        win_paths = list(local.glob("Programs/nodejs/node.exe"))
    return detect_tool(
        binaries=("node", "nodejs"),
        paths=(
            "/usr/bin/node",
            "/usr/local/bin/node",
            _home() / ".nvm/current/bin/node",
            *win_paths,
        ),
        process_markers=("/usr/bin/node", ".nvm/versions/node/"),
        exact_process_names=("node",),
    )


def npm_installed() -> bool:
    if _is_mock_installed_in_dev_mode("npm"):
        return True
    local = _win_local()
    win_paths: list[Path] = []
    if local:
        win_paths = list(local.glob("Programs/nodejs/npm.cmd"))
    return detect_tool(
        binaries=("npm", "npm.cmd"),
        paths=(
            "/usr/bin/npm",
            _home() / ".nvm/current/bin/npm",
            _home() / ".local/bin/npm",
            *win_paths,
        ),
        process_markers=("npm-cli.js", "/usr/bin/npm"),
        exact_process_names=("npm",),
    )


def git_installed() -> bool:
    if _is_mock_installed_in_dev_mode("git"):
        return True
    pf_paths = [pf / "Git/bin/git.exe" for pf in _win_pf()]
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
    pf_paths = [pf / "Docker/Docker/resources/bin/docker.exe" for pf in _win_pf()]
    local = _win_local()
    local_docker = [(local / "Docker/Docker/resources/bin/docker.exe")] if local else []
    return detect_tool(
        binaries=("docker", "docker.exe"),
        paths=(
            "/usr/bin/docker",
            "/usr/local/bin/docker",
            "/opt/homebrew/bin/docker",
            "/snap/bin/docker",
            *pf_paths,
            *local_docker,
        ),
        snap_names=("docker",),
        desktop_files=("docker-desktop.desktop",),
        process_markers=("dockerd", "com.docker.backend", "docker desktop"),
        win_reg_keys=("SOFTWARE\\Docker Inc.\\Docker Desktop",),
    )


def java_installed() -> bool:
    if _is_mock_installed_in_dev_mode("java"):
        return True
    pf_paths: list[Path] = []
    for pf in _win_pf():
        pf_paths.extend([pf / "Java", pf / "Eclipse Adoptium", pf / "Microsoft", pf / "OpenJDK"])
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
        win_reg_keys=("SOFTWARE\\JavaSoft\\Java Runtime Environment", "SOFTWARE\\JavaSoft\\JDK"),
    )


def snap_installed() -> bool:
    return detect_tool(
        binaries=("snap",),
        paths=("/usr/bin/snap", "/snap/bin/snap"),
    )


def android_studio_installed() -> bool:
    pf_paths = [pf / "Android/Android Studio/bin/studio64.exe" for pf in _win_pf()]
    local = _win_local()
    local_paths: list[Path] = []
    if local:
        try:
            local_paths = list(local.glob("JetBrains/Toolbox/apps/AndroidStudio*/*/bin/studio64.exe"))
            local_paths += list(local.glob("Programs/Android Studio/bin/studio64.exe"))
        except Exception:
            pass
    return detect_tool(
        binaries=("android-studio", "studio", "studio.sh"),
        paths=(
            "/snap/bin/android-studio",
            "/opt/android-studio/bin/studio.sh",
            "/Applications/Android Studio.app/Contents/MacOS/studio",
            _home() / "android-studio/bin/studio.sh",
            *pf_paths,
            *local_paths,
        ),
        flatpak_ids=("com.google.AndroidStudio",),
        snap_names=("android-studio",),
        desktop_files=("android-studio.desktop", "jetbrains-android-studio.desktop"),
        process_markers=("android-studio", "studio64.exe", "Android Studio"),
        win_reg_keys=("SOFTWARE\\Android Studio",),
    )


def vscode_installed() -> bool:
    if _is_mock_installed_in_dev_mode("code") or _is_mock_installed_in_dev_mode("vscode"):
        return True
    pf_paths: list[Path] = []
    for pf in _win_pf():
        pf_paths.extend([
            pf / "Microsoft VS Code/bin/code.cmd",
            pf / "Microsoft VS Code/Code.exe",
            pf / "Programs/Microsoft VS Code/bin/code.cmd",
        ])
    local = _win_local()
    if local:
        pf_paths.extend([
            local / "Programs/Microsoft VS Code/Code.exe",
            local / "Programs/Microsoft VS Code/bin/code.cmd",
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
        win_reg_keys=("SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\code.exe",),
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
    local = _win_local()
    win_poetry = [(local / "Programs/Python/Scripts/poetry.exe")] if local else []
    return detect_tool(
        binaries=("poetry",),
        paths=(
            "/usr/bin/poetry",
            "/usr/local/bin/poetry",
            _home() / ".local/bin/poetry",
            _home() / ".poetry/bin/poetry",
            _home() / "AppData/Roaming/Python/Scripts/poetry.exe",
            *win_poetry,
        )
    )


def pnpm_installed() -> bool:
    if _is_mock_installed_in_dev_mode("pnpm"):
        return True
    local = _win_local()
    win_pnpm = [(local / "pnpm/pnpm.exe")] if local else []
    return detect_tool(
        binaries=("pnpm", "pnpm.cmd"),
        paths=(
            "/usr/bin/pnpm",
            "/usr/local/bin/pnpm",
            _home() / ".local/share/pnpm/pnpm",
            _home() / ".local/bin/pnpm",
            _home() / ".nvm/current/bin/pnpm",
            *win_pnpm,
        )
    )


def ollama_installed() -> bool:
    if _is_mock_installed_in_dev_mode("ollama"):
        return True
    local = _win_local()
    win_paths: list[Path] = []
    if local:
        win_paths = [local / "Programs/Ollama/ollama.exe", local / "Ollama/ollama.exe"]
    return detect_tool(
        binaries=("ollama",),
        paths=(
            "/usr/bin/ollama",
            "/usr/local/bin/ollama",
            "/usr/share/ollama",
            *win_paths,
        ),
        win_reg_keys=("SOFTWARE\\Ollama",),
    )


def rust_installed() -> bool:
    if _is_mock_installed_in_dev_mode("rust"):
        return True
    home = _home()
    return detect_tool(
        binaries=("rustc", "rustup"),
        paths=(
            "/usr/bin/rustc",
            "/usr/local/bin/rustc",
            home / ".cargo/bin/rustc",
            home / ".cargo/bin/rustc.exe",
        ),
    )


def go_installed() -> bool:
    if _is_mock_installed_in_dev_mode("go"):
        return True
    pf_go = [pf / "Go/bin/go.exe" for pf in _win_pf()]
    return detect_tool(
        binaries=("go",),
        paths=(
            "/usr/local/go/bin/go",
            "/usr/bin/go",
            "/opt/homebrew/bin/go",
            _home() / "go/bin/go",
            *pf_go,
        ),
    )


def chrome_installed() -> bool:
    local = _win_local()
    win_paths: list[Path] = []
    if local:
        win_paths = [local / "Google/Chrome/Application/chrome.exe"]
    pf_chrome = [pf / "Google/Chrome/Application/chrome.exe" for pf in _win_pf()]
    return detect_tool(
        binaries=("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"),
        paths=(
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/opt/google/chrome/google-chrome",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            *win_paths,
            *pf_chrome,
        ),
        desktop_files=("google-chrome.desktop", "chromium.desktop"),
        win_reg_keys=("SOFTWARE\\Google\\Chrome",),
    )


def firefox_installed() -> bool:
    pf_ff = [pf / "Mozilla Firefox/firefox.exe" for pf in _win_pf()]
    return detect_tool(
        binaries=("firefox",),
        paths=(
            "/usr/bin/firefox",
            "/usr/lib/firefox/firefox",
            "/Applications/Firefox.app/Contents/MacOS/firefox",
            *pf_ff,
        ),
        snap_names=("firefox",),
        desktop_files=("firefox.desktop",),
        win_reg_keys=("SOFTWARE\\Mozilla\\Mozilla Firefox",),
    )


def brave_installed() -> bool:
    local = _win_local()
    win_paths: list[Path] = []
    if local:
        win_paths = [local / "BraveSoftware/Brave-Browser/Application/brave.exe"]
    return detect_tool(
        binaries=("brave-browser", "brave"),
        paths=(
            "/usr/bin/brave-browser",
            "/opt/brave.com/brave/brave-browser",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            *win_paths,
        ),
        desktop_files=("brave-browser.desktop",),
        win_reg_keys=("SOFTWARE\\BraveSoftware\\Brave-Browser",),
    )


def slack_installed() -> bool:
    local = _win_local()
    win_paths: list[Path] = []
    if local:
        win_paths = [local / "slack/slack.exe"]
    return detect_tool(
        binaries=("slack",),
        paths=(
            "/usr/bin/slack",
            "/Applications/Slack.app/Contents/MacOS/Slack",
            *win_paths,
        ),
        snap_names=("slack",),
        flatpak_ids=("com.slack.Slack",),
        desktop_files=("slack.desktop",),
    )


def postman_installed() -> bool:
    local = _win_local()
    win_paths: list[Path] = []
    if local:
        win_paths = [local / "Postman/Postman.exe"]
    return detect_tool(
        binaries=("postman",),
        paths=(
            "/usr/bin/postman",
            "/Applications/Postman.app/Contents/MacOS/Postman",
            *win_paths,
        ),
        snap_names=("postman",),
        flatpak_ids=("com.getpostman.Postman",),
        desktop_files=("postman.desktop",),
    )


def dbeaver_installed() -> bool:
    pf_db = [pf / "DBeaver/dbeaver.exe" for pf in _win_pf()]
    return detect_tool(
        binaries=("dbeaver",),
        paths=(
            "/usr/bin/dbeaver",
            "/usr/share/dbeaver/dbeaver",
            "/Applications/DBeaver.app/Contents/MacOS/dbeaver",
            *pf_db,
        ),
        snap_names=("dbeaver-ce",),
        flatpak_ids=("io.dbeaver.DBeaverCommunity",),
        desktop_files=("dbeaver-ce.desktop", "dbeaver.desktop"),
    )


def pycharm_installed() -> bool:
    local = _win_local()
    local_paths: list[Path] = []
    if local:
        try:
            local_paths = list(local.glob("JetBrains/Toolbox/apps/PyCharm*/*/bin/pycharm64.exe"))
            local_paths += list(local.glob("Programs/PyCharm*/bin/pycharm64.exe"))
        except Exception:
            pass
    return detect_tool(
        binaries=("pycharm", "pycharm-community", "charm"),
        paths=(
            "/usr/bin/pycharm",
            "/opt/pycharm/bin/pycharm.sh",
            "/Applications/PyCharm.app/Contents/MacOS/pycharm",
            "/Applications/PyCharm CE.app/Contents/MacOS/pycharm",
            *local_paths,
        ),
        snap_names=("pycharm-community", "pycharm-professional"),
        flatpak_ids=("com.jetbrains.PyCharm-Community",),
        desktop_files=("pycharm.desktop", "pycharm-community.desktop"),
    )


def sublime_installed() -> bool:
    pf_sub = [pf / "Sublime Text/subl.exe" for pf in _win_pf()]
    return detect_tool(
        binaries=("subl", "sublime_text", "sublime-text"),
        paths=(
            "/usr/bin/subl",
            "/opt/sublime_text/sublime_text",
            "/Applications/Sublime Text.app/Contents/SharedSupport/bin/subl",
            *pf_sub,
        ),
        snap_names=("sublime-text",),
        desktop_files=("sublime_text.desktop",),
        win_reg_keys=("SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\subl.exe",),
    )


def neovim_installed() -> bool:
    if _is_mock_installed_in_dev_mode("neovim"):
        return True
    pf_nv = [pf / "Neovim/bin/nvim.exe" for pf in _win_pf()]
    local = _win_local()
    local_nv = [(local / "Programs/Neovim/bin/nvim.exe")] if local else []
    return detect_tool(
        binaries=("nvim",),
        paths=(
            "/usr/bin/nvim",
            "/usr/local/bin/nvim",
            "/opt/homebrew/bin/nvim",
            *pf_nv,
            *local_nv,
        ),
        snap_names=("nvim",),
        desktop_files=("nvim.desktop",),
    )


def gh_installed() -> bool:
    local = _win_local()
    win_gh: list[Path] = []
    if local:
        try:
            win_gh = list(local.glob("Programs/gh/bin/gh.exe"))
        except Exception:
            pass
    return detect_tool(
        binaries=("gh", "gh.exe"),
        paths=(
            "/usr/bin/gh",
            "/usr/local/bin/gh",
            "/opt/homebrew/bin/gh",
            *win_gh,
        ),
        win_reg_keys=("SOFTWARE\\GitHub CLI",),
    )


def fzf_installed() -> bool:
    return detect_tool(
        binaries=("fzf",),
        paths=(
            "/usr/bin/fzf",
            "/usr/local/bin/fzf",
            _home() / ".fzf/bin/fzf",
        ),
    )


def jq_installed() -> bool:
    pf_jq = [pf / "jq/jq.exe" for pf in _win_pf()]
    return detect_tool(
        binaries=("jq", "jq.exe"),
        paths=(
            "/usr/bin/jq",
            "/usr/local/bin/jq",
            *pf_jq,
        ),
    )


def tmux_installed() -> bool:
    return detect_tool(
        binaries=("tmux",),
        paths=("/usr/bin/tmux", "/usr/local/bin/tmux"),
    )


def htop_installed() -> bool:
    return detect_tool(
        binaries=("htop",),
        paths=("/usr/bin/htop", "/usr/local/bin/htop"),
    )
