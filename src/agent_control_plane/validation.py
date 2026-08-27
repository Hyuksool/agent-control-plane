from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from .executor import CommandSpec, SafeExecutor
from .models import CommandResult, ValidationSummary


class _Digest(Protocol):
    def update(self, data: bytes, /) -> None: ...


class CommandValidator:
    def __init__(
        self,
        executor: SafeExecutor,
        *,
        fail_fast: bool = True,
        protected_paths: tuple[str, ...] = (),
    ) -> None:
        self.executor = executor
        self.fail_fast = fail_fast
        self.protected_paths = protected_paths

    def snapshot_integrity(self, workspace: Path) -> dict[str, str]:
        snapshot: dict[str, str] = {}
        for relative_name in self.protected_paths:
            candidate = _protected_candidate(workspace, relative_name)
            if not candidate.exists():
                raise ValueError(f"protected path does not exist: {relative_name}")
            snapshot[relative_name] = _hash_path(candidate)
        return snapshot

    def validate(
        self,
        commands: tuple[tuple[str, ...], ...],
        workspace: Path,
        *,
        timeout_seconds: float | None = None,
        integrity_snapshot: Mapping[str, str] | None = None,
    ) -> ValidationSummary:
        effective_timeout = min(
            timeout_seconds or self.executor.policy.max_timeout_seconds,
            self.executor.policy.max_timeout_seconds,
        )
        checks = []
        if integrity_snapshot:
            integrity = self._check_integrity(workspace, integrity_snapshot)
            checks.append(integrity)
            if integrity.exit_code != 0:
                return ValidationSummary(tuple(checks))
        for argv in commands:
            result = self.executor.run(
                CommandSpec(argv=argv, cwd=workspace, timeout_seconds=effective_timeout)
            )
            checks.append(result)
            if self.fail_fast and (
                result.exit_code != 0 or result.timed_out or result.policy_reason is not None
            ):
                break
        return ValidationSummary(tuple(checks))

    def _check_integrity(
        self,
        workspace: Path,
        snapshot: Mapping[str, str],
    ) -> CommandResult:
        changed = False
        for relative_name, expected_hash in snapshot.items():
            try:
                current_hash = _hash_path(_protected_candidate(workspace, relative_name))
            except (OSError, ValueError):
                changed = True
                break
            if current_hash != expected_hash:
                changed = True
                break
        identity = "\x00".join(sorted(snapshot))
        return CommandResult(
            command_hash=hashlib.sha256(f"integrity:{identity}".encode()).hexdigest(),
            exit_code=126 if changed else 0,
            duration_ms=0,
            stdout_hash=hashlib.sha256(b"").hexdigest(),
            stderr_hash=hashlib.sha256(b"").hexdigest(),
            stdout_bytes=0,
            stderr_bytes=0,
            policy_reason="protected_path_modified" if changed else None,
        )


def _protected_candidate(workspace: Path, relative_name: str) -> Path:
    relative = Path(relative_name)
    if not relative_name or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("protected paths must be non-empty and relative")
    root = workspace.resolve()
    candidate = root
    for part in relative.parts:
        if part in {"", "."}:
            continue
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("protected path must not contain symlinks")
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError("protected path escapes workspace") from exc
    return candidate


def _hash_path(path: Path) -> str:
    if path.is_symlink():
        raise ValueError("protected path must not be a symlink")
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(b"file\x00")
        _update_file_hash(digest, path)
        return digest.hexdigest()
    if not path.is_dir():
        raise ValueError("protected path must be a file or directory")
    digest.update(b"directory\x00")
    for child in sorted(path.rglob("*")):
        if child.is_symlink():
            raise ValueError("protected tree must not contain symlinks")
        if child.is_file():
            digest.update(str(child.relative_to(path)).encode("utf-8"))
            digest.update(b"\x00")
            _update_file_hash(digest, child)
    return digest.hexdigest()


def _update_file_hash(digest: _Digest, path: Path) -> None:
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            digest.update(chunk)
