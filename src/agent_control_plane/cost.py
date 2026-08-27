from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .models import ModelProfile, TokenUsage


@dataclass
class CostLedger:
    entries: list[tuple[str, Decimal, bool]] = field(default_factory=list)

    def record(self, profile: ModelProfile, usage: TokenUsage, succeeded: bool) -> Decimal:
        cost = profile.estimate_cost(usage.input_tokens, usage.output_tokens)
        self.entries.append((profile.key, cost, succeeded))
        return cost

    @property
    def total(self) -> Decimal:
        return sum((entry[1] for entry in self.entries), start=Decimal("0")).quantize(
            Decimal("0.000001")
        )

    @property
    def failed_cost(self) -> Decimal:
        return sum(
            (cost for _, cost, succeeded in self.entries if not succeeded),
            start=Decimal("0"),
        ).quantize(Decimal("0.000001"))

    def remaining(self, budget: Decimal) -> Decimal:
        return max(Decimal("0"), budget - self.total)
