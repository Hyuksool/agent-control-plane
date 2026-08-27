from __future__ import annotations

import sys
import time
from decimal import Decimal
from pathlib import Path

from agent_control_plane.adapters import ScriptedAction, ScriptedAdapter
from agent_control_plane.executor import SafeExecutor
from agent_control_plane.learning import OutcomeStore
from agent_control_plane.models import (
    AdapterResponse,
    AttemptStatus,
    RiskLevel,
    RunStatus,
    StepKind,
    TaskRequest,
    TaskStep,
    TokenUsage,
)
from agent_control_plane.orchestrator import ControlPlane
from agent_control_plane.policy import ExecutionPolicy
from agent_control_plane.registry import ProviderRegistry
from agent_control_plane.router import PolicyRouter
from agent_control_plane.trace import TraceWriter
from agent_control_plane.validation import CommandValidator


def make_request(workspace: Path, *, budget: str = "0.02", wall: float = 5) -> TaskRequest:
    return TaskRequest(
        request_id="req",
        team_id="private-team-id",
        instruction="write approved result without leaking this instruction",
        workspace=workspace,
        max_cost_usd=Decimal(budget),
        max_attempts_per_step=2,
        max_wall_seconds=wall,
    )


def make_step() -> TaskStep:
    return TaskStep(
        step_id="edit",
        kind=StepKind.EDIT,
        instruction="edit result",
        required_capabilities=frozenset({"edit"}),
        risk=RiskLevel.LOW,
        validation_commands=((sys.executable, "check.py"),),
        max_attempts=2,
        max_output_tokens=100,
    )


def make_plane(tmp_path, profiles, adapters, *, protected_paths=()) -> ControlPlane:
    rules = ExecutionPolicy(
        workspace_root=tmp_path,
        allowed_executables=frozenset({Path(sys.executable).name}),
    )
    outcomes = OutcomeStore(
        tmp_path / ".agent-control-plane/outcomes.sqlite3",
        team_hash_key=b"0123456789abcdef0123456789abcdef",
    )
    router = PolicyRouter(ProviderRegistry(profiles), history=outcomes)
    return ControlPlane(
        router=router,
        adapters=adapters,
        validator=CommandValidator(
            SafeExecutor(rules),
            protected_paths=tuple(protected_paths),
        ),
        outcomes=outcomes,
        trace=TraceWriter(tmp_path / ".agent-control-plane/trace.jsonl"),
    )


def test_validation_failure_escalates_and_counts_both_costs(
    tmp_path, cheap_profile, strong_profile
) -> None:
    (tmp_path / "check.py").write_text(
        "from pathlib import Path\n"
        "raise SystemExit(0 if Path('result.txt').read_text() == 'approved' else 1)\n",
        encoding="utf-8",
    )
    cheap = ScriptedAdapter(
        (ScriptedAction(True, TokenUsage(100, 50), {"result.txt": "wrong"}, "cheap"),)
    )
    strong = ScriptedAdapter(
        (ScriptedAction(True, TokenUsage(100, 50), {"result.txt": "approved"}, "strong"),)
    )
    plane = make_plane(
        tmp_path,
        [cheap_profile, strong_profile],
        {cheap_profile.key: cheap, strong_profile.key: strong},
    )
    report = plane.run(make_request(tmp_path), (make_step(),))
    assert report.status == RunStatus.SUCCEEDED
    assert [item.model_key for item in report.attempts] == [
        cheap_profile.key,
        strong_profile.key,
    ]
    assert [item.status for item in report.attempts] == [
        AttemptStatus.VALIDATION_FAILED,
        AttemptStatus.SUCCEEDED,
    ]
    assert report.total_cost_usd == sum(
        (item.cost_usd for item in report.attempts), start=Decimal("0")
    )
    trace_text = (tmp_path / ".agent-control-plane/trace.jsonl").read_text()
    assert "private-team-id" not in trace_text
    assert "write approved result" not in trace_text
    assert "wrong" not in trace_text


def test_preflight_budget_blocks_every_candidate(tmp_path, strong_profile) -> None:
    (tmp_path / "check.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    plane = make_plane(
        tmp_path,
        [strong_profile],
        {strong_profile.key: ScriptedAdapter((ScriptedAction(True, TokenUsage(1, 1)),))},
    )
    report = plane.run(make_request(tmp_path, budget="0.000001"), (make_step(),))
    assert report.status == RunStatus.BUDGET_EXCEEDED
    assert report.attempts == ()


def test_actual_usage_overrun_stops_run(tmp_path, strong_profile) -> None:
    (tmp_path / "check.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    adapter = ScriptedAdapter((ScriptedAction(True, TokenUsage(10_000, 10_000)),))
    plane = make_plane(tmp_path, [strong_profile], {strong_profile.key: adapter})
    report = plane.run(make_request(tmp_path, budget="0.01"), (make_step(),))
    assert report.status == RunStatus.BUDGET_EXCEEDED
    assert report.attempts[0].status == AttemptStatus.BUDGET_EXCEEDED


class SlowAdapter:
    def execute(self, step, workspace, context):
        del step, workspace, context
        time.sleep(0.03)
        return AdapterResponse(True, TokenUsage(1, 1), "a" * 64)


def test_single_attempt_cannot_exceed_run_wall_time(tmp_path, cheap_profile) -> None:
    step = TaskStep(
        step_id="plan",
        kind=StepKind.PLAN,
        instruction="plan",
        required_capabilities=frozenset({"plan"}),
        risk=RiskLevel.LOW,
        max_attempts=1,
        max_output_tokens=10,
    )
    plane = make_plane(tmp_path, [cheap_profile], {cheap_profile.key: SlowAdapter()})
    report = plane.run(make_request(tmp_path, wall=0.005), (step,))
    assert report.status == RunStatus.TIMED_OUT


class TamperingFailureAdapter:
    def execute(self, step, workspace, context):
        del step, context
        (workspace / "check.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
        return AdapterResponse(False, TokenUsage(1, 1), "b" * 64, "claimed_failure")


def test_failed_adapter_cannot_hide_protected_validator_tampering(
    tmp_path, cheap_profile, strong_profile
) -> None:
    (tmp_path / "check.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
    plane = make_plane(
        tmp_path,
        [cheap_profile, strong_profile],
        {
            cheap_profile.key: TamperingFailureAdapter(),
            strong_profile.key: ScriptedAdapter((ScriptedAction(True, TokenUsage(1, 1)),)),
        },
        protected_paths=("check.py",),
    )

    report = plane.run(make_request(tmp_path), (make_step(),))

    assert report.status == RunStatus.POLICY_DENIED
    assert report.stopped_reason == "protected_path_modified"
    assert len(report.attempts) == 1
    assert report.attempts[0].status == AttemptStatus.POLICY_DENIED
