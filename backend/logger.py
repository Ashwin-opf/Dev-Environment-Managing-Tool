"""
Logger – Structured JSON log for all PC Doctor actions.
Writes one JSON line per action to pc_doctor.log.
"""
import json
import datetime
import os
from pathlib import Path

def get_log_file() -> Path:
    log_dir = os.getenv("LOG_PATH", "").strip()
    if log_dir:
        path = Path(log_dir) / "pc_doctor.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return Path(__file__).parent / "pc_doctor.log"


LOG_FILE = get_log_file()


def _read_log_lines() -> list[str]:
    if not LOG_FILE.exists():
        return []
    return [line.strip() for line in LOG_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_log_lines(lines: list[str]) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def clear_logs() -> int:
    count = len(_read_log_lines())
    _write_log_lines([])
    return count


def delete_log_lines(*, delete_all: bool = False, indices: list[int] | None = None) -> int:
    lines = _read_log_lines()
    if not lines:
        return 0
    if delete_all:
        removed = len(lines)
        _write_log_lines([])
        return removed
    if not indices:
        return 0
    keep = {idx for idx in range(len(lines)) if idx not in set(indices)}
    new_lines = [lines[idx] for idx in range(len(lines)) if idx in keep]
    removed = len(lines) - len(new_lines)
    _write_log_lines(new_lines)
    return removed


def export_logs_text() -> str:
    return "\n".join(_read_log_lines())


def log_action(action: str, command: str, detail: str = "", friendly_summary: str = "") -> None:
    """Append a single log entry to pc_doctor.log."""
    entry = {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
        "action": action,
        "command": command,
        "detail": detail,
        "friendly_summary": friendly_summary,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
