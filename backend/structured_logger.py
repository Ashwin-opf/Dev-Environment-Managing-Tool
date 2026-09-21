"""
structured_logger.py — Authoritative 16-Field Structured Action Logger for PC Doctor.

Enforces:
- Every action log entry contains all 16 required architectural fields:
  1. timestamp
  2. operation
  3. application
  4. identity
  5. recipe_id
  6. source
  7. status
  8. message
  9. command
  10. return_code
  11. versions
  12. verification
  13. tier
  14. trust
  15. risk
  16. confidence
- Secret / API Token / Credential Redaction.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def get_log_file() -> Path:
    try:
        from runtime_paths import get_log_file as _get_path
        return _get_path()
    except Exception:
        log_dir = os.getenv("LOG_PATH", "").strip()
        if log_dir:
            path = Path(log_dir) / "pc_doctor.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        return Path(__file__).parent / "pc_doctor.log"


LOG_FILE = get_log_file()

# Regex patterns for sensitive data redaction (tokens, API keys, credentials)
SECRET_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{12,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s&|]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(--?(?:api[_\-]?key|token|password|secret)\s*[:=\s]\s*)[^\s&|]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(api[_\-]?key\s*[:=]\s*)[a-zA-Z0-9_\-]{10,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(token\s*[:=]\s*)[a-zA-Z0-9_\-]{10,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(password\s*[:=]\s*)[^\s&|]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(secret\s*[:=]\s*)[^\s&|]+"), r"\1[REDACTED]"),
    (re.compile(r"AIza[0-9A-Za-z-_]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"sk-(?:proj-)?[a-zA-Z0-9_-]{10,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"ghp_[a-zA-Z0-9]{20,}"), "[REDACTED_TOKEN]"),
    (re.compile(r"github_pat_[a-zA-Z0-9_]{20,}"), "[REDACTED_TOKEN]"),
]


def redact_secrets(val: Any) -> Any:
    """Recursively redacts secrets, credentials, and API tokens from strings or collections."""
    if val is None:
        return None
    if isinstance(val, str):
        clean = val
        for pat, rep in SECRET_PATTERNS:
            clean = pat.sub(rep, clean)
        return clean
    if isinstance(val, dict):
        return {k: redact_secrets(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [redact_secrets(item) for item in val]
    return val


class StructuredLogger:
    """Authoritative structured logger logging JSON-lines."""

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self.log_path = log_path or LOG_FILE

    def log_event(
        self,
        operation: str,
        application: str,
        identity: str,
        status: str,
        message: str,
        command: str = "",
        recipe_id: str = "",
        source: str = "STATIC_DB",
        return_code: Optional[int] = None,
        versions: Optional[Dict[str, Any]] = None,
        verification: Optional[Dict[str, Any]] = None,
        tier: str = "TIER_1_FAST",
        trust: float = 1.0,
        risk: float = 0.2,
        confidence: float = 1.0,
        details: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Logs structured action entry with all 16 required fields."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "operation": str(operation),
            "application": str(application),
            "identity": str(identity),
            "recipe_id": str(recipe_id),
            "source": str(source),
            "status": str(status),
            "message": redact_secrets(str(message)),
            "command": redact_secrets(str(command)),
            "return_code": return_code,
            "versions": redact_secrets(versions) if versions else {},
            "verification": redact_secrets(verification) if verification else {},
            "tier": str(tier),
            "trust": round(float(trust), 2),
            "risk": round(float(risk), 2),
            "confidence": round(float(confidence), 2),
            "details": redact_secrets(details) if details else {},
        }

        # Backwards compatibility fields for frontend UI log viewer
        entry["action"] = entry["status"]
        entry["detail"] = entry["message"]
        entry["friendly_summary"] = f"[{entry['operation']}] {entry['application']} — {entry['status']}"

        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

        return entry


# Global singleton structured logger
structured_logger = StructuredLogger()
