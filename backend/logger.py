"""
Logger – Structured JSON log for all PC Doctor actions.
Writes one JSON line per action to pc_doctor.log conforming to Section 22.
"""
from __future__ import annotations

import json
import datetime
import os
from pathlib import Path
from typing import Any, Dict, Optional


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


def log_action(
    action: str,
    command: str,
    detail: str = "",
    friendly_summary: str = "",
    *,
    operation: str = "MUTATION",
    application: str = "",
    identity: str = "",
    recipe_id: str = "",
    source: str = "STATIC_DB",
    return_code: Optional[int] = None,
    versions: Optional[Dict[str, Any]] = None,
    verification: Optional[Dict[str, Any]] = None,
    tier: str = "TIER_1_FAST",
    trust: float = 1.0,
    risk: float = 0.2,
    confidence: float = 1.0,
) -> None:
    """Append a single structured log entry conforming to the 16 architectural fields."""
    try:
        from structured_logger import structured_logger
        structured_logger.log_event(
            operation=operation,
            application=application or friendly_summary or "System",
            identity=identity or application,
            status=action,
            message=detail or friendly_summary,
            command=command,
            recipe_id=recipe_id,
            source=source,
            return_code=return_code,
            versions=versions,
            verification=verification,
            tier=tier,
            trust=trust,
            risk=risk,
            confidence=confidence,
        )
    except Exception:
        # Fallback raw write with secret redaction
        try:
            from structured_logger import redact_secrets
        except Exception:
            def redact_secrets(s): return s

        entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "action": str(action),
            "command": redact_secrets(str(command)),
            "detail": redact_secrets(str(detail)),
            "friendly_summary": redact_secrets(str(friendly_summary)),
            "operation": str(operation),
            "application": redact_secrets(str(application or "System")),
            "identity": str(identity),
            "recipe_id": str(recipe_id),
            "source": str(source),
            "status": str(action),
            "message": redact_secrets(str(detail)),
            "return_code": return_code,
            "versions": redact_secrets(versions or {}),
            "verification": redact_secrets(verification or {}),
            "tier": str(tier),
            "trust": trust,
            "risk": risk,
            "confidence": confidence,
        }
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
