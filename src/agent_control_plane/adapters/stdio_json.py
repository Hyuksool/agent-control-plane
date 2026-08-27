from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from ..models import AdapterResponse, TaskStep, TokenUsage
from ..process_io import run_bounded_process
from .base import AdapterContext


@dataclass(frozen=True)
class StdioBridgeConfig:
    command: tuple[str, ...]
    allowed_executable_names: frozenset[str]
    timeout_seconds: float = 120.0
    max_request_bytes: int = 1_000_000
    max_response_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("bridge command must not be empty")
        if Path(self.command[0]).name not in self.allowed_executable_names:
            raise ValueError("bridge executable is not allowlisted")
        if (
            not isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
            or self.max_request_bytes < 1
            or self.max_response_bytes < 1
        ):
            raise ValueError("bridge limits must be positive")


class StdioJsonAdapter:
    """Runs a pre-approved local bridge; request JSON goes over stdin, never a shell."""

    def __init__(self, config: StdioBridgeConfig) -> None:
        self.config = config

    def execute(
        self,
        step: TaskStep,
        workspace: Path,
        context: AdapterContext,
    ) -> AdapterResponse:
        payload = json.dumps(
            {
                "run_id": context.run_id,
                "attempt": context.attempt,
                "step_id": step.step_id,
                "kind": step.kind.value,
                "instruction": step.instruction,
                "workspace": str(workspace),
                "required_capabilities": sorted(step.required_capabilities),
                "risk": step.risk.name.lower(),
                "max_output_tokens": step.max_output_tokens,
                "previous_outputs": list(context.previous_outputs),
                "previous_failure_code": context.previous_failure_code,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > self.config.max_request_bytes:
            return _failure(payload, "bridge_request_limit")
        env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "VIRTUAL_ENV"}
        }
        completed = run_bounded_process(
            self.config.command,
            cwd=workspace,
            environment=env,
            timeout_seconds=self.config.timeout_seconds,
            max_output_bytes=self.config.max_response_bytes,
            input_bytes=payload,
        )
        if completed.timed_out:
            return _failure(completed.stdout, "bridge_timeout")
        if completed.output_limited:
            return _failure(completed.stdout, "bridge_output_limit")
        if completed.returncode != 0:
            return _failure(completed.stdout, "bridge_nonzero_exit")
        try:
            data = json.loads(completed.stdout.decode("utf-8"))
            output = str(data.get("output", ""))
            return AdapterResponse(
                success=bool(data["success"]),
                usage=TokenUsage(int(data["input_tokens"]), int(data["output_tokens"])),
                response_hash=hashlib.sha256(output.encode("utf-8")).hexdigest(),
                error_code=str(data["error_code"]) if data.get("error_code") else None,
                ephemeral_output=output,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return _failure(completed.stdout, "bridge_invalid_json")


def _failure(body: bytes, code: str) -> AdapterResponse:
    return AdapterResponse(
        False,
        TokenUsage(0, 0),
        hashlib.sha256(body).hexdigest(),
        code,
    )
