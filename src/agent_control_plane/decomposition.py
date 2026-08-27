from __future__ import annotations

from dataclasses import dataclass

from .models import RiskLevel, StepKind, TaskRequest, TaskStep


@dataclass(frozen=True)
class HeuristicDecomposer:
    validation_commands: tuple[tuple[str, ...], ...]
    edit_risk: RiskLevel = RiskLevel.MEDIUM

    def decompose(self, request: TaskRequest) -> tuple[TaskStep, ...]:
        return (
            TaskStep(
                step_id="plan",
                kind=StepKind.PLAN,
                instruction=(
                    "Plan the requested change without editing files: "
                    f"{request.instruction}"
                ),
                required_capabilities=frozenset({"plan"}),
                risk=RiskLevel.LOW,
                max_attempts=1,
                max_output_tokens=1_000,
            ),
            TaskStep(
                step_id="edit",
                kind=StepKind.EDIT,
                instruction=(
                    "Implement the requested change in the workspace: "
                    f"{request.instruction}"
                ),
                required_capabilities=frozenset({"edit"}),
                risk=self.edit_risk,
                validation_commands=self.validation_commands,
                max_attempts=request.max_attempts_per_step,
                max_output_tokens=3_000,
            ),
            TaskStep(
                step_id="review",
                kind=StepKind.REVIEW,
                instruction="Review the implementation against the request and validation results.",
                required_capabilities=frozenset({"review"}),
                risk=RiskLevel.LOW,
                max_attempts=1,
                max_output_tokens=1_000,
            ),
        )
