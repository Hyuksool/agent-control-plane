from __future__ import annotations

import argparse
import json
import sys
import uuid
from decimal import Decimal
from pathlib import Path

from .adapters import ScriptedAction, ScriptedAdapter
from .benchmark import run_benchmark
from .config import ConfigError, load_config
from .executor import SafeExecutor
from .learning import OutcomeStore
from .models import (
    ModelProfile,
    RiskLevel,
    RunStatus,
    StepKind,
    TaskRequest,
    TaskStep,
    TokenUsage,
)
from .orchestrator import ControlPlane
from .policy import ExecutionPolicy
from .registry import ProviderRegistry
from .router import PolicyRouter
from .runtime import run_configured_task
from .trace import TraceWriter
from .validation import CommandValidator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-control-plane",
        description="Policy-driven control plane for coding agents",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="run an offline escalation demo")
    demo.add_argument("--workspace", type=Path, required=True)

    subparsers.add_parser("benchmark", help="run deterministic baseline comparison")

    run = subparsers.add_parser("run", help="run configured local provider bridges")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--workspace", type=Path, required=True)
    run.add_argument("--team-id", required=True)
    run.add_argument(
        "--task-file",
        default="-",
        help="UTF-8 task file, or '-' to read from stdin (default)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "demo":
            payload = run_demo(args.workspace)
            print(json.dumps(payload, indent=2, sort_keys=True))
            report_payload = payload.get("report")
            succeeded = isinstance(report_payload, dict) and (
                report_payload.get("status") == RunStatus.SUCCEEDED.value
            )
            return 0 if succeeded else 1
        if args.command == "benchmark":
            payload = run_benchmark()
            print(json.dumps(payload, indent=2, sort_keys=True))
            acceptance = payload.get("acceptance")
            accepted = isinstance(acceptance, dict) and acceptance.get("accepted") is True
            return 0 if accepted else 1
        if args.command == "run":
            instruction = _read_task(args.task_file)
            config = load_config(args.config.resolve())
            report = run_configured_task(
                config,
                workspace=args.workspace.resolve(),
                instruction=instruction,
                team_id=args.team_id,
            )
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
            return 0 if report.status == RunStatus.SUCCEEDED else 1
    except (ConfigError, OSError, ValueError) as exc:
        print(
            json.dumps({"error": type(exc).__name__, "message": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    raise AssertionError("unreachable command")


def run_demo(parent: Path) -> dict[str, object]:
    parent = parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    workspace = parent / f"run-{uuid.uuid4().hex[:12]}"
    workspace.mkdir()
    (workspace / "check.py").write_text(
        "from pathlib import Path\n"
        "raise SystemExit(0 if Path('result.txt').read_text() == 'approved' else 1)\n",
        encoding="utf-8",
    )
    cheap, strong = _demo_profiles()
    cheap_adapter = ScriptedAdapter(
        (
            ScriptedAction(
                True,
                TokenUsage(100, 50),
                {"result.txt": "wrong"},
                "cheap-attempt",
            ),
        )
    )
    strong_adapter = ScriptedAdapter(
        (
            ScriptedAction(
                True,
                TokenUsage(100, 50),
                {"result.txt": "approved"},
                "strong-attempt",
            ),
        )
    )
    state = workspace / ".agent-control-plane"
    outcomes = OutcomeStore(
        state / "outcomes.sqlite3",
        team_hash_key=b"offline-demo-team-hash-key-32-bytes",
    )
    policy = ExecutionPolicy(
        workspace_root=workspace,
        allowed_executables=frozenset({Path(sys.executable).name}),
    )
    plane = ControlPlane(
        router=PolicyRouter(ProviderRegistry([cheap, strong]), history=outcomes),
        adapters={cheap.key: cheap_adapter, strong.key: strong_adapter},
        validator=CommandValidator(SafeExecutor(policy)),
        outcomes=outcomes,
        trace=TraceWriter(state / "trace.jsonl"),
    )
    request = TaskRequest(
        request_id="offline-demo",
        team_id="offline-demo-team",
        instruction="write an approved deterministic result",
        workspace=workspace,
        max_cost_usd=Decimal("0.02"),
        max_attempts_per_step=2,
        max_wall_seconds=10,
    )
    step = TaskStep(
        step_id="edit",
        kind=StepKind.EDIT,
        instruction="write result.txt",
        required_capabilities=frozenset({"edit"}),
        risk=RiskLevel.LOW,
        validation_commands=((sys.executable, "check.py"),),
        max_attempts=2,
        max_output_tokens=100,
    )
    report = plane.run(request, (step,))
    return {
        "mode": "offline_deterministic_demo",
        "workspace": str(workspace),
        "report": report.to_dict(),
        "trace": str(state / "trace.jsonl"),
        "limitations": "No real provider was called; this proves control-flow behavior only.",
    }


def _read_task(value: str) -> str:
    instruction = sys.stdin.read() if value == "-" else Path(value).read_text(encoding="utf-8")
    if not instruction.strip():
        raise ValueError("task input must not be empty")
    return instruction


def _demo_profiles() -> tuple[ModelProfile, ModelProfile]:
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


if __name__ == "__main__":
    raise SystemExit(main())
