"""
runtime_paths.py — Platform-Neutral Runtime Directory & Path Resolution
========================================================================
Authoritative resolution of runtime data, config, log, and database paths
for PC Doctor across Windows, Linux, and macOS.

Guarantees:
- Zero hardcoded developer paths (no user home directories, no scratch directories).
- Compliance with OS standard data/cache/config hierarchies:
    * Windows: %LOCALAPPDATA%\\PC Doctor (data/logs), %APPDATA%\\PC Doctor (config)
    * macOS: ~/Library/Application Support/PC Doctor, ~/Library/Logs/PC Doctor
    * Linux: $XDG_DATA_HOME/pc-doctor, $XDG_CONFIG_HOME/pc-doctor, $XDG_STATE_HOME/pc-doctor
- Environment variable overrides for testing and containerized execution:
    * PC_DOCTOR_DATA_DIR
    * PC_DOCTOR_LOG_DIR / LOG_PATH
    * PC_DOCTOR_CONFIG_DIR
    * DB_PATH
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent


def is_packaged() -> bool:
    """Return True if running inside a packaged binary (PyInstaller, Tauri bundle, etc.)."""
    return getattr(sys, "frozen", False) or "PC_DOCTOR_PACKAGED" in os.environ


def get_user_data_dir() -> Path:
    """
    Return the platform-specific directory for persistent application data.
    - Windows: %LOCALAPPDATA%\\PC Doctor
    - macOS: ~/Library/Application Support/PC Doctor
    - Linux: $XDG_DATA_HOME/pc-doctor or ~/.local/share/pc-doctor
    """
    override = os.getenv("PC_DOCTOR_DATA_DIR", "").strip()
    if override:
        p = Path(override)
        p.mkdir(parents=True, exist_ok=True)
        return p

    system = platform.system()
    if system == "Windows":
        local_app_data = os.getenv("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        p = base / "PC Doctor"
    elif system == "Darwin":
        p = Path.home() / "Library" / "Application Support" / "PC Doctor"
    else:
        xdg = os.getenv("XDG_DATA_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"
        p = base / "pc-doctor"

    p.mkdir(parents=True, exist_ok=True)
    return p


def get_user_log_dir() -> Path:
    """
    Return the platform-specific directory for application log files.
    - Windows: %LOCALAPPDATA%\\PC Doctor\\logs
    - macOS: ~/Library/Logs/PC Doctor
    - Linux: $XDG_STATE_HOME/pc-doctor/logs or ~/.local/state/pc-doctor/logs
    """
    override = os.getenv("PC_DOCTOR_LOG_DIR", "").strip() or os.getenv("LOG_PATH", "").strip()
    if override:
        p = Path(override)
        p.mkdir(parents=True, exist_ok=True)
        return p

    system = platform.system()
    if system == "Windows":
        p = get_user_data_dir() / "logs"
    elif system == "Darwin":
        p = Path.home() / "Library" / "Logs" / "PC Doctor"
    else:
        xdg_state = os.getenv("XDG_STATE_HOME")
        base = Path(xdg_state) if xdg_state else Path.home() / ".local" / "state"
        p = base / "pc-doctor" / "logs"

    p.mkdir(parents=True, exist_ok=True)
    return p


def get_user_config_dir() -> Path:
    """
    Return the platform-specific directory for user configuration files.
    - Windows: %APPDATA%\\PC Doctor or %LOCALAPPDATA%\\PC Doctor\\config
    - macOS: ~/Library/Application Support/PC Doctor
    - Linux: $XDG_CONFIG_HOME/pc-doctor or ~/.config/pc-doctor
    """
    override = os.getenv("PC_DOCTOR_CONFIG_DIR", "").strip()
    if override:
        p = Path(override)
        p.mkdir(parents=True, exist_ok=True)
        return p

    system = platform.system()
    if system == "Windows":
        app_data = os.getenv("APPDATA")
        base = Path(app_data) if app_data else Path.home() / "AppData" / "Roaming"
        p = base / "PC Doctor"
    elif system == "Darwin":
        p = Path.home() / "Library" / "Application Support" / "PC Doctor"
    else:
        xdg_config = os.getenv("XDG_CONFIG_HOME")
        base = Path(xdg_config) if xdg_config else Path.home() / ".config"
        p = base / "pc-doctor"

    p.mkdir(parents=True, exist_ok=True)
    return p


def get_log_file() -> Path:
    """Return the authoritative path to pc_doctor.log."""
    override_log = os.getenv("LOG_PATH", "").strip()
    if override_log:
        p = Path(override_log)
        if p.is_dir() or not p.suffix:
            p = p / "pc_doctor.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # In local repo development when not packaged and running from scratch/pc-doc
    if not is_packaged() and not os.getenv("PC_DOCTOR_LOG_DIR"):
        local_log = BASE_DIR / "pc_doctor.log"
        return local_log

    return get_user_log_dir() / "pc_doctor.log"


def get_ai_config_dir() -> Path:
    """Return the configuration directory for AI provider credentials and models."""
    override = os.getenv("PC_DOCTOR_AI_CONFIG_DIR", "").strip()
    if override:
        p = Path(override)
        p.mkdir(parents=True, exist_ok=True)
        return p

    if not is_packaged() and not os.getenv("PC_DOCTOR_CONFIG_DIR"):
        return BASE_DIR / ".pc_doctor_ai_config"

    return get_user_config_dir() / "ai_config"


def get_bundled_static_db_path() -> Optional[Path]:
    """Locate the bundled static reference database (read-only reference knowledge)."""
    candidates = [
        BASE_DIR / "knowledge_static.db",
        BASE_DIR.parent / "resources" / "backend" / "knowledge_static.db",
        Path("knowledge_static.db"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def get_bundled_runtime_db_path() -> Optional[Path]:
    """Locate the seed runtime database (knowledge.db template)."""
    candidates = [
        BASE_DIR / "knowledge.db",
        BASE_DIR.parent / "resources" / "backend" / "knowledge.db",
        Path("knowledge.db"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def get_static_db_path() -> Path:
    """Return the authoritative path for knowledge_static.db."""
    bundled = get_bundled_static_db_path()
    if bundled:
        return bundled
    return BASE_DIR / "knowledge_static.db"


def get_runtime_db_path() -> Path:
    """
    Return the authoritative path for the runtime database (knowledge.db).
    - If DB_PATH is explicitly set in environment, respects it unconditionally.
    - If in packaged production mode or PC_DOCTOR_DATA_DIR set: uses get_user_data_dir() / 'knowledge.db'
    - In development mode: defaults to BASE_DIR / 'knowledge.db'
    """
    db_env = os.getenv("DB_PATH", "").strip()
    if db_env:
        return Path(db_env)

    if is_packaged() or os.getenv("PC_DOCTOR_DATA_DIR"):
        return get_user_data_dir() / "knowledge.db"

    # Default to local backend/knowledge.db during development/testing
    return BASE_DIR / "knowledge.db"
