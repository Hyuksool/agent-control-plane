from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from ..models import AdapterResponse, TaskStep, TokenUsage
from .base import AdapterContext


@dataclass(frozen=True)
class ScriptedAction:
    success: bool
    usage: TokenUsage
    files: Mapping[str, str] = field(default_factory=dict)
    output: str = ""
    error_code: str | None = None


class ScriptedAdapter:
    """Offline adapter used for deterministic integration tests and demos."""

    def __init__(self, actions: tuple[ScriptedAction, ...]) -> None:
        if not actions:
            raise ValueError("at least one scripted action is required")
        self.actions = actions
        self.calls = 0

    def execute(
        self,
        step: TaskStep,
        workspace: Path,
        context: AdapterContext,
    ) -> AdapterResponse:
        del step, context
        action = self.actions[min(self.calls, len(self.actions) - 1)]
        self.calls += 1
        root = workspace.resolve()
        for relative_name, content in action.files.items():
            candidate = (root / relative_name).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise ValueError("scripted action attempted workspace escape") from exc
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text(content, encoding="utf-8")
        return AdapterResponse(
            success=action.success,
            usage=action.usage,
            response_hash=hashlib.sha256(action.output.encode("utf-8")).hexdigest(),
            error_code=action.error_code,
            ephemeral_output=action.output,
        )
