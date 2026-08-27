from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..models import AdapterResponse, TaskStep


@dataclass(frozen=True)
class AdapterContext:
    run_id: str
    attempt: int
    previous_outputs: tuple[str, ...] = field(default_factory=tuple, repr=False)
    previous_failure_code: str | None = None


class ProviderAdapter(Protocol):
    def execute(
        self,
        step: TaskStep,
        workspace: Path,
        context: AdapterContext,
    ) -> AdapterResponse: ...
