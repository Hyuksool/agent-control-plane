from __future__ import annotations

import os
import secrets
from pathlib import Path

from .adapters import StdioJsonAdapter
from .config import AppConfig
from .decomposition import HeuristicDecomposer
from .executor import SafeExecutor
from .learning import OutcomeStore
from .models import RunReport, TaskRequest
from .orchestrator import ControlPlane
from .policy import ExecutionPolicy
from .registry import ProviderRegistry
from .router import PolicyRouter
from .trace import TraceWriter
from .validation import CommandValidator


def run_configured_task(
    config: AppConfig,
    *,
    workspace: Path,
    instruction: str,
    team_id: str,
) -> RunReport:
    root = workspace.resolve()
    if not root.is_dir():
        raise ValueError("workspace must exist and be a directory")
    state = root / ".agent-control-plane"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state, 0o700)
    key = _load_or_create_hash_key(state / "team-hash.key")
    outcomes = OutcomeStore(state / "outcomes.sqlite3", team_hash_key=key)
    registry = ProviderRegistry(binding.profile for binding in config.models)
    adapters = {
        binding.profile.key: StdioJsonAdapter(config.bridges[binding.adapter])
        for binding in config.models
    }
    policy = ExecutionPolicy(
        workspace_root=root,
        allowed_executables=config.execution.allowed_executables,
        allowed_python_modules=config.execution.allowed_python_modules,
        max_timeout_seconds=config.execution.max_timeout_seconds,
        max_output_bytes=config.execution.max_output_bytes,
    )
    plane = ControlPlane(
        router=PolicyRouter(registry, history=outcomes),
        adapters=adapters,
        validator=CommandValidator(
            SafeExecutor(policy),
            protected_paths=config.execution.protected_paths,
        ),
        outcomes=outcomes,
        trace=TraceWriter(state / "trace.jsonl"),
    )
    request = TaskRequest(
        request_id=secrets.token_hex(8),
        team_id=team_id,
        instruction=instruction,
        workspace=root,
        category=config.run.category,
        max_cost_usd=config.run.max_cost_usd,
        max_attempts_per_step=config.run.max_attempts_per_step,
        max_wall_seconds=config.run.max_wall_seconds,
    )
    steps = HeuristicDecomposer(
        config.validation_commands,
        edit_risk=config.run.edit_risk,
    ).decompose(request)
    return plane.run(request, steps)


def _load_or_create_hash_key(path: Path) -> bytes:
    if path.exists():
        if path.is_symlink():
            raise ValueError("team hash key must not be a symlink")
        os.chmod(path, 0o600)
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            key = os.read(descriptor, 33)
        finally:
            os.close(descriptor)
        if len(key) != 32:
            raise ValueError("invalid team hash key")
        return key
    key = secrets.token_bytes(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, key)
    finally:
        os.close(descriptor)
    return key
