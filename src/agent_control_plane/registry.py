from __future__ import annotations

from collections.abc import Iterable

from .models import ModelProfile, RiskLevel


class ProviderRegistry:
    def __init__(self, profiles: Iterable[ModelProfile] = ()) -> None:
        self._profiles: dict[str, ModelProfile] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: ModelProfile) -> None:
        if profile.key in self._profiles:
            raise ValueError(f"duplicate model profile: {profile.key}")
        self._profiles[profile.key] = profile

    def get(self, key: str) -> ModelProfile:
        try:
            return self._profiles[key]
        except KeyError as exc:
            raise KeyError(f"unknown model profile: {key}") from exc

    def all(self) -> tuple[ModelProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))

    def eligible(
        self,
        capabilities: frozenset[str],
        risk: RiskLevel,
    ) -> tuple[ModelProfile, ...]:
        return tuple(
            profile
            for profile in self.all()
            if profile.enabled
            and capabilities.issubset(profile.capabilities)
            and risk <= profile.max_risk
        )
