from __future__ import annotations

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from pathlib import Path

from .adapters import StdioBridgeConfig
from .models import ModelProfile, RiskLevel


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ModelBinding:
    profile: ModelProfile
    adapter: str


@dataclass(frozen=True)
class ExecutionConfig:
    allowed_executables: frozenset[str]
    allowed_python_modules: frozenset[str]
    protected_paths: tuple[str, ...]
    max_timeout_seconds: float
    max_output_bytes: int

    def __post_init__(self) -> None:
        if not self.allowed_executables:
            raise ValueError("allowed_executables must not be empty")
        if not isfinite(self.max_timeout_seconds) or self.max_timeout_seconds <= 0:
            raise ValueError("max_timeout_seconds must be finite and positive")
        if self.max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")


@dataclass(frozen=True)
class RunConfig:
    max_cost_usd: Decimal
    max_attempts_per_step: int
    max_wall_seconds: float
    edit_risk: RiskLevel
    category: str

    def __post_init__(self) -> None:
        if not self.max_cost_usd.is_finite() or self.max_cost_usd <= 0:
            raise ValueError("max_cost_usd must be finite and positive")
        if self.max_attempts_per_step < 1:
            raise ValueError("max_attempts_per_step must be at least one")
        if not isfinite(self.max_wall_seconds) or self.max_wall_seconds <= 0:
            raise ValueError("max_wall_seconds must be finite and positive")
        if not self.category.strip():
            raise ValueError("category must not be empty")


@dataclass(frozen=True)
class AppConfig:
    run: RunConfig
    execution: ExecutionConfig
    validation_commands: tuple[tuple[str, ...], ...]
    models: tuple[ModelBinding, ...]
    bridges: dict[str, StdioBridgeConfig]


def load_config(path: Path) -> AppConfig:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot load configuration: {type(exc).__name__}") from exc

    try:
        run_raw = raw.get("run", {})
        execution_raw = raw["execution"]
        run = RunConfig(
            max_cost_usd=Decimal(str(run_raw.get("max_cost_usd", "1.00"))),
            max_attempts_per_step=int(run_raw.get("max_attempts_per_step", 2)),
            max_wall_seconds=float(run_raw.get("max_wall_seconds", 300)),
            edit_risk=_risk(str(run_raw.get("edit_risk", "medium"))),
            category=str(run_raw.get("category", "coding")),
        )
        execution = ExecutionConfig(
            allowed_executables=frozenset(str(v) for v in execution_raw["allowed_executables"]),
            allowed_python_modules=frozenset(
                str(v)
                for v in execution_raw.get("allowed_python_modules", ["pytest", "compileall"])
            ),
            protected_paths=tuple(str(v) for v in execution_raw.get("protected_paths", [])),
            max_timeout_seconds=float(execution_raw.get("max_timeout_seconds", 120)),
            max_output_bytes=int(execution_raw.get("max_output_bytes", 1_000_000)),
        )
        validation_commands = tuple(
            tuple(str(token) for token in entry["argv"])
            for entry in raw.get("validation", [])
        )
        bridges = {
            name: StdioBridgeConfig(
                command=tuple(str(token) for token in value["command"]),
                allowed_executable_names=frozenset(
                    str(token) for token in value["allowed_executable_names"]
                ),
                timeout_seconds=float(value.get("timeout_seconds", 120)),
                max_request_bytes=int(value.get("max_request_bytes", 1_000_000)),
                max_response_bytes=int(value.get("max_response_bytes", 1_000_000)),
            )
            for name, value in raw.get("bridges", {}).items()
        }
        models = tuple(
            ModelBinding(
                profile=ModelProfile(
                    provider=str(entry["provider"]),
                    model=str(entry["model"]),
                    capabilities=frozenset(str(v) for v in entry["capabilities"]),
                    max_risk=_risk(str(entry["max_risk"])),
                    input_cost_per_1k=Decimal(str(entry["input_cost_per_1k"])),
                    output_cost_per_1k=Decimal(str(entry["output_cost_per_1k"])),
                    quality_prior=Decimal(str(entry["quality_prior"])),
                    latency_ms=int(entry.get("latency_ms", 1_000)),
                    enabled=bool(entry.get("enabled", True)),
                ),
                adapter=str(entry["adapter"]),
            )
            for entry in raw["models"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"invalid configuration: {type(exc).__name__}") from exc

    if not models:
        raise ConfigError("at least one model is required")
    missing = sorted({binding.adapter for binding in models} - set(bridges))
    if missing:
        raise ConfigError(f"model references unknown bridge: {missing[0]}")
    if not validation_commands:
        raise ConfigError("at least one validation command is required")
    return AppConfig(run, execution, validation_commands, models, bridges)


def _risk(value: str) -> RiskLevel:
    try:
        return RiskLevel[value.strip().upper()]
    except KeyError as exc:
        raise ConfigError(f"invalid risk level: {value}") from exc
