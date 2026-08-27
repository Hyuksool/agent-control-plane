from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import IntEnum, StrEnum
from math import isfinite
from pathlib import Path
from typing import Any


class RiskLevel(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class StepKind(StrEnum):
    PLAN = "plan"
    EDIT = "edit"
    VALIDATE = "validate"
    REVIEW = "review"


class AttemptStatus(StrEnum):
    SUCCEEDED = "succeeded"
    ADAPTER_FAILED = "adapter_failed"
    VALIDATION_FAILED = "validation_failed"
    POLICY_DENIED = "policy_denied"
    BUDGET_EXCEEDED = "budget_exceeded"
    TIMED_OUT = "timed_out"


class RunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    POLICY_DENIED = "policy_denied"
    BUDGET_EXCEEDED = "budget_exceeded"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class TaskRequest:
    request_id: str
    team_id: str
    instruction: str
    workspace: Path
    category: str = "coding"
    max_cost_usd: Decimal = Decimal("1.00")
    max_attempts_per_step: int = 2
    max_wall_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise ValueError("request_id must not be empty")
        if not self.team_id.strip():
            raise ValueError("team_id must not be empty")
        if not self.instruction.strip():
            raise ValueError("instruction must not be empty")
        if not self.workspace.is_absolute():
            raise ValueError("workspace must be an absolute path")
        if not self.category.strip():
            raise ValueError("category must not be empty")
        if not self.max_cost_usd.is_finite() or self.max_cost_usd <= 0:
            raise ValueError("max_cost_usd must be finite and positive")
        if self.max_attempts_per_step < 1:
            raise ValueError("max_attempts_per_step must be at least one")
        if not isfinite(self.max_wall_seconds) or self.max_wall_seconds <= 0:
            raise ValueError("max_wall_seconds must be finite and positive")

@dataclass(frozen=True)
class TaskStep:
    step_id: str
    kind: StepKind
    instruction: str
    required_capabilities: frozenset[str]
    risk: RiskLevel = RiskLevel.LOW
    validation_commands: tuple[tuple[str, ...], ...] = ()
    max_attempts: int = 2
    max_output_tokens: int = 2_000

    def __post_init__(self) -> None:
        if not self.step_id.strip() or not self.instruction.strip():
            raise ValueError("step_id and instruction must not be empty")
        if self.max_attempts < 1 or self.max_output_tokens < 1:
            raise ValueError("step limits must be positive")


@dataclass(frozen=True)
class ModelProfile:
    provider: str
    model: str
    capabilities: frozenset[str]
    max_risk: RiskLevel
    input_cost_per_1k: Decimal
    output_cost_per_1k: Decimal
    quality_prior: Decimal
    latency_ms: int = 1_000
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip():
            raise ValueError("provider and model must not be empty")
        if (
            not self.input_cost_per_1k.is_finite()
            or not self.output_cost_per_1k.is_finite()
            or self.input_cost_per_1k < 0
            or self.output_cost_per_1k < 0
        ):
            raise ValueError("model cost must be finite and non-negative")
        if not self.quality_prior.is_finite() or not (
            Decimal("0") <= self.quality_prior <= Decimal("1")
        ):
            raise ValueError("quality_prior must be between zero and one")
        if self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.model}"

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts cannot be negative")
        cost = (
            self.input_cost_per_1k * Decimal(input_tokens) / Decimal(1_000)
            + self.output_cost_per_1k * Decimal(output_tokens) / Decimal(1_000)
        )
        return cost.quantize(Decimal("0.000001"))


@dataclass(frozen=True)
class TeamStats:
    attempts: int = 0
    successes: int = 0
    total_cost_usd: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.attempts < 0 or self.successes < 0 or self.successes > self.attempts:
            raise ValueError("invalid aggregate outcome counts")
        if not self.total_cost_usd.is_finite() or self.total_cost_usd < 0:
            raise ValueError("aggregate cost must be finite and non-negative")

    @property
    def success_rate(self) -> Decimal:
        if self.attempts == 0:
            return Decimal("0.5")
        return Decimal(self.successes) / Decimal(self.attempts)


@dataclass(frozen=True)
class RouteDecision:
    selected: ModelProfile | None
    score: Decimal | None
    reasons: tuple[str, ...]
    rejected: tuple[str, ...] = ()
    estimated_cost_usd: Decimal = Decimal("0")

    @property
    def allowed(self) -> bool:
        return self.selected is not None


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token counts cannot be negative")


@dataclass(frozen=True)
class AdapterResponse:
    success: bool
    usage: TokenUsage
    response_hash: str
    error_code: str | None = None
    ephemeral_output: str = field(default="", repr=False, compare=False)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class CommandResult:
    command_hash: str
    exit_code: int
    duration_ms: int
    stdout_hash: str
    stderr_hash: str
    stdout_bytes: int
    stderr_bytes: int
    timed_out: bool = False
    policy_reason: str | None = None


@dataclass(frozen=True)
class ValidationSummary:
    checks: tuple[CommandResult, ...] = ()

    @property
    def success(self) -> bool:
        return bool(self.checks) and all(
            check.exit_code == 0 and not check.timed_out and check.policy_reason is None
            for check in self.checks
        )

    @classmethod
    def not_required(cls) -> ValidationSummary:
        return cls(())


@dataclass(frozen=True)
class AttemptRecord:
    step_id: str
    attempt: int
    model_key: str
    status: AttemptStatus
    cost_usd: Decimal
    usage: TokenUsage
    duration_ms: int
    response_hash: str
    validation: ValidationSummary
    reason_code: str | None = None


@dataclass(frozen=True)
class RunReport:
    run_id: str
    request_hash: str
    team_hash: str
    status: RunStatus
    total_cost_usd: Decimal
    duration_ms: int
    attempts: tuple[AttemptRecord, ...]
    stopped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "request_hash": self.request_hash,
            "team_hash": self.team_hash,
            "status": self.status.value,
            "total_cost_usd": str(self.total_cost_usd),
            "duration_ms": self.duration_ms,
            "stopped_reason": self.stopped_reason,
            "attempts": [
                {
                    "step_id": item.step_id,
                    "attempt": item.attempt,
                    "model_key": item.model_key,
                    "status": item.status.value,
                    "cost_usd": str(item.cost_usd),
                    "input_tokens": item.usage.input_tokens,
                    "output_tokens": item.usage.output_tokens,
                    "duration_ms": item.duration_ms,
                    "response_hash": item.response_hash,
                    "reason_code": item.reason_code,
                    "validation": [
                        {
                            "command_hash": check.command_hash,
                            "exit_code": check.exit_code,
                            "timed_out": check.timed_out,
                            "policy_reason": check.policy_reason,
                        }
                        for check in item.validation.checks
                    ],
                }
                for item in self.attempts
            ],
        }
