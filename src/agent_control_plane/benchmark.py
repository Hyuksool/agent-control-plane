from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .adapters import ScriptedAction, ScriptedAdapter
from .executor import SafeExecutor
from .learning import OutcomeStore
from .models import ModelProfile, RiskLevel, RunStatus, StepKind, TaskRequest, TaskStep, TokenUsage
from .orchestrator import ControlPlane
from .policy import ExecutionPolicy
from .registry import ProviderRegistry
from .router import PolicyRouter
from .validation import CommandValidator


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    risk: RiskLevel
    cheap_passes: bool


_CASES = (
    BenchmarkCase("low_risk_success", RiskLevel.LOW, True),
    BenchmarkCase("validation_escalation", RiskLevel.LOW, False),
    BenchmarkCase("high_risk_direct_strong", RiskLevel.HIGH, False),
)


def run_benchmark() -> dict[str, Any]:
    baseline = _run_strategy("always_strong")
    policy = _run_strategy("policy_router")
    accepted = (
        policy["completed"] >= baseline["completed"]
        and Decimal(policy["total_cost_usd"]) < Decimal(baseline["total_cost_usd"])
        and policy["policy_violations"] == 0
    )
    return {
        "benchmark": "deterministic_offline_v1",
        "cases": len(_CASES),
        "baseline": baseline,
        "policy_router": policy,
        "acceptance": {
            "completion_not_worse": policy["completed"] >= baseline["completed"],
            "total_cost_lower": Decimal(policy["total_cost_usd"])
            < Decimal(baseline["total_cost_usd"]),
            "policy_violations_zero": policy["policy_violations"] == 0,
            "accepted": accepted,
        },
        "limitations": "Offline deterministic evidence; not a real-provider quality claim.",
    }


def _run_strategy(strategy: str) -> dict[str, Any]:
    completed = 0
    total_cost = Decimal("0")
    attempts = 0
    escalations = 0
    policy_violations = 0
    case_reports = []
    for case in _CASES:
        report = _run_case(strategy, case)
        completed += int(report.status == RunStatus.SUCCEEDED)
        total_cost += report.total_cost_usd
        attempts += len(report.attempts)
        escalations += max(0, len(report.attempts) - 1)
        policy_violations += sum(item.status.value == "policy_denied" for item in report.attempts)
        case_reports.append(
            {
                "name": case.name,
                "status": report.status.value,
                "attempts": len(report.attempts),
                "cost_usd": str(report.total_cost_usd),
            }
        )
    return {
        "completed": completed,
        "total": len(_CASES),
        "completion_rate": str(Decimal(completed) / Decimal(len(_CASES))),
        "total_cost_usd": str(total_cost.quantize(Decimal("0.000001"))),
        "attempts": attempts,
        "escalations": escalations,
        "policy_violations": policy_violations,
        "case_reports": case_reports,
    }


def _run_case(strategy: str, case: BenchmarkCase):
    with tempfile.TemporaryDirectory(prefix="agent-control-benchmark-") as temporary:
        workspace = Path(temporary)
        (workspace / "check.py").write_text(
            "from pathlib import Path\n"
            "raise SystemExit(0 if Path('result.txt').read_text() == 'approved' else 1)\n",
            encoding="utf-8",
        )
        cheap, strong = _profiles()
        cheap_value = "approved" if case.cheap_passes else "wrong"
        adapters = {
            cheap.key: ScriptedAdapter(
                (
                    ScriptedAction(
                        True,
                        TokenUsage(1_000, 500),
                        {"result.txt": cheap_value},
                        "cheap-output",
                    ),
                )
            ),
            strong.key: ScriptedAdapter(
                (
                    ScriptedAction(
                        True,
                        TokenUsage(1_000, 500),
                        {"result.txt": "approved"},
                        "strong-output",
                    ),
                )
            ),
        }
        profiles = [strong] if strategy == "always_strong" else [cheap, strong]
        outcomes = OutcomeStore(
            workspace / "outcomes.sqlite3",
            team_hash_key=b"benchmark-team-hash-key-32-byte!",
        )
        policy = ExecutionPolicy(
            workspace_root=workspace,
            allowed_executables=frozenset({Path(sys.executable).name}),
        )
        plane = ControlPlane(
            router=PolicyRouter(ProviderRegistry(profiles), history=outcomes),
            adapters={profile.key: adapters[profile.key] for profile in profiles},
            validator=CommandValidator(SafeExecutor(policy)),
            outcomes=outcomes,
        )
        request = TaskRequest(
            request_id=f"{strategy}-{case.name}",
            team_id="benchmark-team",
            instruction="deterministic benchmark task",
            workspace=workspace,
            max_cost_usd=Decimal("0.10"),
            max_attempts_per_step=2,
            max_wall_seconds=10,
        )
        step = TaskStep(
            step_id="edit",
            kind=StepKind.EDIT,
            instruction="write approved result",
            required_capabilities=frozenset({"edit"}),
            risk=case.risk,
            validation_commands=((sys.executable, "check.py"),),
            max_attempts=2,
            max_output_tokens=500,
        )
        return plane.run(request, (step,))


def _profiles() -> tuple[ModelProfile, ModelProfile]:
    cheap = ModelProfile(
        provider="offline",
        model="cheap",
        capabilities=frozenset({"edit"}),
        max_risk=RiskLevel.MEDIUM,
        input_cost_per_1k=Decimal("0.001"),
        output_cost_per_1k=Decimal("0.002"),
        quality_prior=Decimal("0.55"),
        latency_ms=100,
    )
    strong = ModelProfile(
        provider="offline",
        model="strong",
        capabilities=frozenset({"edit"}),
        max_risk=RiskLevel.CRITICAL,
        input_cost_per_1k=Decimal("0.010"),
        output_cost_per_1k=Decimal("0.030"),
        quality_prior=Decimal("0.95"),
        latency_ms=500,
    )
    return cheap, strong
