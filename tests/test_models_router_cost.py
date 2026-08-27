from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from agent_control_plane.cost import CostLedger
from agent_control_plane.models import (
    RiskLevel,
    StepKind,
    TaskRequest,
    TaskStep,
    TokenUsage,
)
from agent_control_plane.registry import ProviderRegistry
from agent_control_plane.router import PolicyRouter


def request(workspace: Path, *, budget: str = "1") -> TaskRequest:
    return TaskRequest(
        request_id="req-1",
        team_id="team-private",
        instruction="make a safe change",
        workspace=workspace,
        max_cost_usd=Decimal(budget),
    )


def step(*, risk: RiskLevel = RiskLevel.LOW) -> TaskStep:
    return TaskStep(
        step_id="edit",
        kind=StepKind.EDIT,
        instruction="edit",
        required_capabilities=frozenset({"edit"}),
        risk=risk,
        max_output_tokens=100,
    )


def test_request_requires_absolute_workspace() -> None:
    with pytest.raises(ValueError, match="absolute"):
        request(Path("relative"))


def test_registry_rejects_duplicate(cheap_profile) -> None:
    registry = ProviderRegistry([cheap_profile])
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(cheap_profile)


def test_router_chooses_cheaper_safe_model(tmp_path, cheap_profile, strong_profile) -> None:
    router = PolicyRouter(ProviderRegistry([strong_profile, cheap_profile]))
    decision = router.route(
        request(tmp_path),
        step(),
        remaining_budget=Decimal("1"),
        estimated_input_tokens=100,
    )
    assert decision.selected == cheap_profile
    assert "selected_by_policy_score" in decision.reasons


def test_high_risk_requires_strong_model(tmp_path, cheap_profile, strong_profile) -> None:
    router = PolicyRouter(ProviderRegistry([cheap_profile, strong_profile]))
    decision = router.route(
        request(tmp_path),
        step(risk=RiskLevel.HIGH),
        remaining_budget=Decimal("1"),
        estimated_input_tokens=100,
    )
    assert decision.selected == strong_profile


def test_router_escalates_when_cheap_is_excluded(tmp_path, cheap_profile, strong_profile) -> None:
    router = PolicyRouter(ProviderRegistry([cheap_profile, strong_profile]))
    decision = router.route(
        request(tmp_path),
        step(),
        remaining_budget=Decimal("1"),
        estimated_input_tokens=100,
        excluded=frozenset({cheap_profile.key}),
        quality_floor=Decimal("0.550001"),
    )
    assert decision.selected == strong_profile
    assert any("excluded_after_failure" in item for item in decision.rejected)


def test_router_rejects_candidates_over_remaining_budget(
    tmp_path, cheap_profile, strong_profile
) -> None:
    router = PolicyRouter(ProviderRegistry([cheap_profile, strong_profile]))
    decision = router.route(
        request(tmp_path),
        step(),
        remaining_budget=Decimal("0.000001"),
        estimated_input_tokens=100,
    )
    assert not decision.allowed
    assert all("budget" in item for item in decision.rejected)


def test_cost_ledger_counts_failed_attempts(cheap_profile, strong_profile) -> None:
    ledger = CostLedger()
    first = ledger.record(cheap_profile, TokenUsage(1_000, 500), succeeded=False)
    second = ledger.record(strong_profile, TokenUsage(1_000, 500), succeeded=True)
    assert ledger.total == first + second
    assert ledger.failed_cost == first
    assert first > 0
