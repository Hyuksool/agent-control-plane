from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from .models import PolicyDecision

_SHELL_MARKERS = (";", "&&", "||", "`", "$(", "\n", "\r", "\x00")


@dataclass(frozen=True)
class ExecutionPolicy:
    workspace_root: Path
    allowed_executables: frozenset[str] = frozenset(
        {"python", "python3", "pytest", "ruff", "git"}
    )
    allowed_python_modules: frozenset[str] = frozenset({"pytest", "compileall"})
    allowed_environment_keys: frozenset[str] = frozenset(
        {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "VIRTUAL_ENV", "PYTHONPATH"}
    )
    denied_git_subcommands: frozenset[str] = frozenset(
        {
            "add",
            "checkout",
            "clean",
            "clone",
            "commit",
            "config",
            "fetch",
            "merge",
            "pull",
            "push",
            "remote",
            "reset",
            "restore",
            "switch",
        }
    )
    max_timeout_seconds: float = 120.0
    max_output_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if not self.workspace_root.is_absolute():
            raise ValueError("workspace_root must be absolute")
        if (
            not isfinite(self.max_timeout_seconds)
            or self.max_timeout_seconds <= 0
            or self.max_output_bytes < 1
        ):
            raise ValueError("execution limits must be positive")

    @property
    def root(self) -> Path:
        return self.workspace_root.resolve()

    def check(self, argv: tuple[str, ...], cwd: Path, timeout_seconds: float) -> PolicyDecision:
        if not argv or any(not isinstance(token, str) or not token for token in argv):
            return PolicyDecision(False, "invalid_argv")
        if timeout_seconds <= 0 or timeout_seconds > self.max_timeout_seconds:
            return PolicyDecision(False, "timeout_out_of_policy")

        try:
            resolved_cwd = cwd.resolve()
            resolved_cwd.relative_to(self.root)
        except (OSError, ValueError):
            return PolicyDecision(False, "cwd_outside_workspace")

        executable = Path(argv[0]).name
        if executable not in self.allowed_executables:
            return PolicyDecision(False, "executable_not_allowed")

        for token in argv:
            if any(marker in token for marker in _SHELL_MARKERS):
                return PolicyDecision(False, "shell_syntax_denied")

        if executable == "git" and len(argv) > 1 and argv[1] in self.denied_git_subcommands:
            return PolicyDecision(False, "mutating_git_command_denied")

        if executable in {"python", "python3"}:
            if "-c" in argv or "-" in argv[1:]:
                return PolicyDecision(False, "inline_python_denied")
            module_index = argv.index("-m") if "-m" in argv else -1
            if module_index >= 0:
                if len(argv) <= module_index + 1:
                    return PolicyDecision(False, "missing_python_module")
                if argv[module_index + 1] not in self.allowed_python_modules:
                    return PolicyDecision(False, "python_module_not_allowed")

        for token in argv[1:]:
            candidate = token.split("=", 1)[-1] if "=" in token else token
            if candidate.startswith(("http://", "https://")):
                return PolicyDecision(False, "network_target_denied")
            if self._looks_like_path(candidate):
                path = Path(candidate)
                resolved = path.resolve() if path.is_absolute() else (resolved_cwd / path).resolve()
                try:
                    resolved.relative_to(self.root)
                except ValueError:
                    return PolicyDecision(False, "argument_path_outside_workspace")

        return PolicyDecision(True, "allowed")

    @staticmethod
    def _looks_like_path(token: str) -> bool:
        return token.startswith(("/", "./", "../", "~")) or "/" in token or token.endswith(
            (".py", ".toml", ".json", ".yaml", ".yml")
        )

    def check_environment(self, keys: set[str]) -> PolicyDecision:
        denied = sorted(keys - self.allowed_environment_keys)
        if denied:
            return PolicyDecision(False, f"environment_key_denied:{denied[0]}")
        return PolicyDecision(True, "allowed")
