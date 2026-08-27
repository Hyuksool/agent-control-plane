from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from .models import ModelProfile, RiskLevel, RouteDecision, TaskRequest, TaskStep, TeamStats
from .registry import ProviderRegistry


class HistoryProvider(Protocol):
    def stats(self, team_id: str, category: str, model_key: str) -> TeamStats: ...


class EmptyHistory:
    def stats(self, team_id: str, category: str, model_key: str) -> TeamStats:
        del team_id, category, model_key
        return TeamStats()


@dataclass(frozen=True)
class RoutingPolicy:
    min_quality_by_risk: dict[RiskLevel, Decimal] = field(
        default_factory=lambda: {
            RiskLevel.LOW: Decimal("0.30"),
            RiskLevel.MEDIUM: Decimal("0.55"),
            RiskLevel.HIGH: Decimal("0.80"),
            RiskLevel.CRITICAL: Decimal("0.95"),
        }
    )
    quality_weight: Decimal = Decimal("0.55")
    history_weight: Decimal = Decimal("0.25")
    cost_weight: Decimal = Decimal("0.35")
    latency_weight: Decimal = Decimal("0.05")
    allowed_providers: frozenset[str] = frozenset()
    allowed_models: frozenset[str] = frozenset()


class PolicyRouter:
    def __init__(
        self,
        registry: ProviderRegistry,
        policy: RoutingPolicy | None = None,
        history: HistoryProvider | None = None,
    ) -> None:
        self.registry = registry
        self.policy = policy or RoutingPolicy()
        self.history = history or EmptyHistory()

    def route(
        self,
        request: TaskRequest,
        step: TaskStep,
        *,
        remaining_budget: Decimal,
        estimated_input_tokens: int,
        excluded: frozenset[str] = frozenset(),
        quality_floor: Decimal | None = None,
    ) -> RouteDecision:
        floor = max(
            self.policy.min_quality_by_risk[step.risk],
            quality_floor or Decimal("0"),
        )
        rejected: list[str] = []
        preliminary: list[tuple[ModelProfile, Decimal, TeamStats]] = []
        candidates = self.registry.eligible(step.required_capabilities, step.risk)

        for profile in candidates:
            if profile.key in excluded:
                rejected.append(f"{profile.key}:excluded_after_failure")
                continue
            if (
                self.policy.allowed_providers
                and profile.provider not in self.policy.allowed_providers
            ):
                rejected.append(f"{profile.key}:provider_not_allowed")
                continue
            if self.policy.allowed_models and profile.key not in self.policy.allowed_models:
                rejected.append(f"{profile.key}:model_not_allowed")
                continue
            if profile.quality_prior < floor:
                rejected.append(f"{profile.key}:quality_below_{floor}")
                continue

            estimated_cost = profile.estimate_cost(
                estimated_input_tokens,
                step.max_output_tokens,
            )
            if estimated_cost > remaining_budget:
                rejected.append(f"{profile.key}:estimated_cost_exceeds_budget")
                continue
            stats = self.history.stats(request.team_id, request.category, profile.key)
            preliminary.append((profile, estimated_cost, stats))

        if not preliminary:
            if not candidates:
                rejected.append("registry:no_capability_or_risk_match")
            return RouteDecision(None, None, ("no_eligible_model",), tuple(sorted(rejected)))

        cost_denominator = max(
            (estimated_cost for _, estimated_cost, _ in preliminary),
            default=Decimal("0.000001"),
        )
        cost_denominator = max(cost_denominator, Decimal("0.000001"))
        ranked: list[tuple[Decimal, Decimal, ModelProfile, tuple[str, ...]]] = []
        for profile, estimated_cost, stats in preliminary:
            cost_ratio = min(Decimal("1"), estimated_cost / cost_denominator)
            latency_ratio = min(Decimal("1"), Decimal(profile.latency_ms) / Decimal(60_000))
            score = (
                profile.quality_prior * self.policy.quality_weight
                + (stats.success_rate - Decimal("0.5")) * self.policy.history_weight
                - cost_ratio * self.policy.cost_weight
                - latency_ratio * self.policy.latency_weight
            ).quantize(Decimal("0.000001"))
            reasons = (
                f"quality={profile.quality_prior}",
                f"team_success={stats.success_rate.quantize(Decimal('0.001'))}",
                f"estimated_cost={estimated_cost}",
                f"relative_cost={cost_ratio.quantize(Decimal('0.001'))}",
                f"latency_ms={profile.latency_ms}",
            )
            ranked.append((score, -estimated_cost, profile, reasons))

        ranked.sort(key=lambda row: (row[0], row[1], row[2].key), reverse=True)
        score, _, selected, selected_reasons = ranked[0]
        return RouteDecision(
            selected=selected,
            score=score,
            reasons=("selected_by_policy_score", *selected_reasons),
            rejected=tuple(sorted(rejected)),
            estimated_cost_usd=selected.estimate_cost(
                estimated_input_tokens,
                step.max_output_tokens,
            ),
        )
