from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal

from .adapters.base import AdapterContext, ProviderAdapter
from .cost import CostLedger
from .learning import OutcomeStore
from .models import (
    AdapterResponse,
    AttemptRecord,
    AttemptStatus,
    RunReport,
    RunStatus,
    TaskRequest,
    TaskStep,
    TokenUsage,
    ValidationSummary,
)
from .router import PolicyRouter
from .trace import TraceWriter
from .validation import CommandValidator


class ControlPlane:
    def __init__(
        self,
        *,
        router: PolicyRouter,
        adapters: Mapping[str, ProviderAdapter],
        validator: CommandValidator,
        outcomes: OutcomeStore,
        trace: TraceWriter | None = None,
    ) -> None:
        self.router = router
        self.adapters = dict(adapters)
        self.validator = validator
        self.outcomes = outcomes
        self.trace = trace

    def run(self, request: TaskRequest, steps: Sequence[TaskStep]) -> RunReport:
        if not request.workspace.exists() or not request.workspace.is_dir():
            raise ValueError("workspace must exist and be a directory")
        if not steps:
            raise ValueError("at least one task step is required")

        run_id = uuid.uuid4().hex
        team_hash = self.outcomes.team_hash(request.team_id)
        request_hash = self.outcomes.request_hash(request.instruction)
        started = time.monotonic()
        ledger = CostLedger()
        records: list[AttemptRecord] = []
        ephemeral_outputs: list[str] = []
        integrity_snapshot = self.validator.snapshot_integrity(request.workspace)
        final_status = RunStatus.SUCCEEDED
        stopped_reason: str | None = None

        self._emit(
            "run_started",
            run_id=run_id,
            request_hash=request_hash,
            team_hash=team_hash,
            category=request.category,
        )

        for step in steps:
            step_succeeded = False
            excluded: set[str] = set()
            quality_floor: Decimal | None = None
            previous_failure_code: str | None = None
            attempt_limit = min(step.max_attempts, request.max_attempts_per_step)

            for attempt_number in range(1, attempt_limit + 1):
                elapsed = time.monotonic() - started
                if elapsed >= request.max_wall_seconds:
                    final_status = RunStatus.TIMED_OUT
                    stopped_reason = "run_wall_time_exceeded"
                    break

                remaining = ledger.remaining(request.max_cost_usd)
                decision = self.router.route(
                    request,
                    step,
                    remaining_budget=remaining,
                    estimated_input_tokens=_estimate_tokens(step.instruction),
                    excluded=frozenset(excluded),
                    quality_floor=quality_floor,
                )
                if not decision.allowed or decision.selected is None:
                    budget_blocked = any("budget" in reason for reason in decision.rejected)
                    final_status = (
                        RunStatus.BUDGET_EXCEEDED if budget_blocked else RunStatus.POLICY_DENIED
                    )
                    stopped_reason = decision.reasons[0]
                    break

                profile = decision.selected
                adapter = self.adapters.get(profile.key)
                adapter_started = time.monotonic()
                if adapter is None:
                    response = AdapterResponse(
                        success=False,
                        usage=TokenUsage(0, 0),
                        response_hash=hashlib.sha256(b"").hexdigest(),
                        error_code="adapter_not_registered",
                    )
                else:
                    try:
                        response = adapter.execute(
                            step,
                            request.workspace,
                            AdapterContext(
                                run_id=run_id,
                                attempt=attempt_number,
                                previous_outputs=tuple(ephemeral_outputs[-3:]),
                                previous_failure_code=previous_failure_code,
                            ),
                        )
                    except Exception as exc:  # adapter boundary: do not leak exception text
                        response = AdapterResponse(
                            success=False,
                            usage=TokenUsage(0, 0),
                            response_hash=hashlib.sha256(type(exc).__name__.encode()).hexdigest(),
                            error_code="adapter_exception",
                        )
                duration_ms = int((time.monotonic() - adapter_started) * 1_000)

                validation_required = bool(step.validation_commands) or bool(integrity_snapshot)
                validation = (
                    self.validator.validate(
                        step.validation_commands if response.success else (),
                        request.workspace,
                        integrity_snapshot=integrity_snapshot,
                    )
                    if validation_required
                    else ValidationSummary.not_required()
                )
                validation_ok = not validation_required or validation.success
                integrity_denied = any(
                    check.policy_reason == "protected_path_modified"
                    for check in validation.checks
                )
                attempt_succeeded = response.success and validation_ok
                attempt_cost = profile.estimate_cost(
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                )
                budget_overrun = ledger.total + attempt_cost > request.max_cost_usd
                wall_overrun = time.monotonic() - started >= request.max_wall_seconds
                ledger.record(
                    profile,
                    response.usage,
                    attempt_succeeded and not budget_overrun and not wall_overrun,
                )

                if budget_overrun:
                    status = AttemptStatus.BUDGET_EXCEEDED
                    reason_code = "actual_cost_exceeded_budget"
                    final_status = RunStatus.BUDGET_EXCEEDED
                    stopped_reason = reason_code
                    attempt_succeeded = False
                elif wall_overrun:
                    status = AttemptStatus.TIMED_OUT
                    reason_code = "run_wall_time_exceeded"
                    final_status = RunStatus.TIMED_OUT
                    stopped_reason = reason_code
                    attempt_succeeded = False
                elif integrity_denied:
                    status = AttemptStatus.POLICY_DENIED
                    reason_code = "protected_path_modified"
                    final_status = RunStatus.POLICY_DENIED
                    stopped_reason = reason_code
                    attempt_succeeded = False
                elif not response.success:
                    status = AttemptStatus.ADAPTER_FAILED
                    reason_code = response.error_code or "adapter_failed"
                elif not validation_ok:
                    timed_out = any(check.timed_out for check in validation.checks)
                    denied = any(check.policy_reason for check in validation.checks)
                    if timed_out:
                        status = AttemptStatus.TIMED_OUT
                        reason_code = "validation_timeout"
                    elif denied:
                        status = AttemptStatus.POLICY_DENIED
                        reason_code = "validation_policy_denied"
                    else:
                        status = AttemptStatus.VALIDATION_FAILED
                        reason_code = "validation_failed"
                else:
                    status = AttemptStatus.SUCCEEDED
                    reason_code = None

                record = AttemptRecord(
                    step_id=step.step_id,
                    attempt=attempt_number,
                    model_key=profile.key,
                    status=status,
                    cost_usd=attempt_cost,
                    usage=response.usage,
                    duration_ms=duration_ms + sum(c.duration_ms for c in validation.checks),
                    response_hash=response.response_hash,
                    validation=validation,
                    reason_code=reason_code,
                )
                records.append(record)
                self.outcomes.record(
                    request.team_id,
                    request.category,
                    profile.key,
                    succeeded=attempt_succeeded,
                    cost_usd=attempt_cost,
                )
                self._emit(
                    "attempt_finished",
                    run_id=run_id,
                    request_hash=request_hash,
                    team_hash=team_hash,
                    category=request.category,
                    step_id=step.step_id,
                    attempt=attempt_number,
                    provider=profile.provider,
                    model=profile.model,
                    status=status,
                    reason_code=reason_code,
                    duration_ms=record.duration_ms,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cost_usd=attempt_cost,
                    validation_passed=validation_ok,
                )

                if budget_overrun or wall_overrun or integrity_denied:
                    break
                if attempt_succeeded:
                    step_succeeded = True
                    if response.ephemeral_output:
                        ephemeral_outputs.append(response.ephemeral_output[:16_384])
                    break

                excluded.add(profile.key)
                quality_floor = min(Decimal("1"), profile.quality_prior + Decimal("0.000001"))
                previous_failure_code = reason_code

            if stopped_reason is not None:
                break
            if not step_succeeded:
                final_status = RunStatus.FAILED
                stopped_reason = f"step_attempts_exhausted:{step.step_id}"
                break

        duration_ms = int((time.monotonic() - started) * 1_000)
        report = RunReport(
            run_id=run_id,
            request_hash=request_hash,
            team_hash=team_hash,
            status=final_status,
            total_cost_usd=ledger.total,
            duration_ms=duration_ms,
            attempts=tuple(records),
            stopped_reason=stopped_reason,
        )
        self._emit(
            "run_finished",
            run_id=run_id,
            request_hash=request_hash,
            team_hash=team_hash,
            category=request.category,
            status=final_status,
            duration_ms=duration_ms,
            cost_usd=ledger.total,
            stopped_reason=stopped_reason,
        )
        return report

    def _emit(self, event: str, **attributes: object) -> None:
        if self.trace is not None:
            self.trace.emit(event, **attributes)


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)
