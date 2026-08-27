from __future__ import annotations

from decimal import Decimal

import pytest

from agent_control_plane.models import ModelProfile, RiskLevel


@pytest.fixture
def cheap_profile() -> ModelProfile:
    return ModelProfile(
        provider="offline",
        model="cheap",
        capabilities=frozenset({"plan", "edit", "review"}),
        max_risk=RiskLevel.MEDIUM,
        input_cost_per_1k=Decimal("0.001"),
        output_cost_per_1k=Decimal("0.002"),
        quality_prior=Decimal("0.55"),
        latency_ms=100,
    )


@pytest.fixture
def strong_profile() -> ModelProfile:
    return ModelProfile(
        provider="offline",
        model="strong",
        capabilities=frozenset({"plan", "edit", "review", "security"}),
        max_risk=RiskLevel.CRITICAL,
        input_cost_per_1k=Decimal("0.010"),
        output_cost_per_1k=Decimal("0.030"),
        quality_prior=Decimal("0.95"),
        latency_ms=500,
    )
