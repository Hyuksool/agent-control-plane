from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .models import CommandResult
from .policy import ExecutionPolicy
from .process_io import run_bounded_process


@dataclass(frozen=True)
class CommandSpec:
    argv: tuple[str, ...]
    cwd: Path
    timeout_seconds: float = 60.0
    environment: Mapping[str, str] = field(default_factory=dict)


class SafeExecutor:
    def __init__(self, policy: ExecutionPolicy) -> None:
        self.policy = policy

    def run(self, spec: CommandSpec) -> CommandResult:
        command_hash = _hash_text("\x00".join(spec.argv))
        decision = self.policy.check(spec.argv, spec.cwd, spec.timeout_seconds)
        env_decision = self.policy.check_environment(set(spec.environment))
        if not decision.allowed or not env_decision.allowed:
            reason = decision.reason if not decision.allowed else env_decision.reason
            return CommandResult(
                command_hash=command_hash,
                exit_code=126,
                duration_ms=0,
                stdout_hash=_hash_bytes(b""),
                stderr_hash=_hash_bytes(b""),
                stdout_bytes=0,
                stderr_bytes=0,
                policy_reason=reason,
            )

        safe_env = {
            key: value
            for key, value in os.environ.items()
            if key in self.policy.allowed_environment_keys
        }
        safe_env.update(spec.environment)
        completed = run_bounded_process(
            spec.argv,
            cwd=spec.cwd,
            environment=safe_env,
            timeout_seconds=spec.timeout_seconds,
            max_output_bytes=self.policy.max_output_bytes,
        )
        policy_reason = "output_limit_exceeded" if completed.output_limited else None
        return CommandResult(
            command_hash=command_hash,
            exit_code=completed.returncode,
            duration_ms=completed.duration_ms,
            stdout_hash=_hash_bytes(completed.stdout),
            stderr_hash=_hash_bytes(completed.stderr),
            stdout_bytes=len(completed.stdout),
            stderr_bytes=len(completed.stderr),
            timed_out=completed.timed_out,
            policy_reason=policy_reason,
        )


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
