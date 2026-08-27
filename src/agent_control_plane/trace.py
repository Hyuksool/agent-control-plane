from __future__ import annotations

import json
import os
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

_ALLOWED_FIELDS = frozenset(
    {
        "run_id",
        "request_hash",
        "team_hash",
        "event",
        "category",
        "step_id",
        "attempt",
        "provider",
        "model",
        "status",
        "reason_code",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "validation_passed",
        "stopped_reason",
    }
)


class TraceWriter:
    def __init__(self, path: Path) -> None:
        if not path.is_absolute():
            raise ValueError("trace path must be absolute")
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        if self.path.is_symlink():
            raise ValueError("trace path must not be a symlink")
        if self.path.exists():
            os.chmod(self.path, 0o600)

    def emit(self, event: str, **attributes: Any) -> None:
        payload = {"event": event, **attributes}
        unknown = set(payload) - _ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"trace field not allowed: {sorted(unknown)[0]}")
        encoded = json.dumps(
            {key: _safe_value(value) for key, value in payload.items()},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        if len(encoded) > 16_384:
            raise ValueError("trace event exceeds size limit")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, encoded)
        finally:
            os.close(descriptor)


def _safe_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 256:
            raise ValueError("trace string exceeds size limit")
        return value
    raise TypeError(f"unsupported trace value: {type(value).__name__}")
