from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent_control_plane.adapters import (
    AdapterContext,
    ScriptedAction,
    ScriptedAdapter,
    StdioBridgeConfig,
    StdioJsonAdapter,
)
from agent_control_plane.models import RiskLevel, StepKind, TaskStep, TokenUsage


def task() -> TaskStep:
    return TaskStep(
        step_id="edit",
        kind=StepKind.EDIT,
        instruction="text with ; shell-looking data",
        required_capabilities=frozenset({"edit"}),
        risk=RiskLevel.LOW,
    )


def test_scripted_adapter_writes_only_inside_workspace(tmp_path) -> None:
    adapter = ScriptedAdapter(
        (
            ScriptedAction(
                True,
                TokenUsage(10, 20),
                files={"nested/result.txt": "ok"},
                output="ephemeral plan",
            ),
        )
    )
    response = adapter.execute(task(), tmp_path, AdapterContext("run", 1))
    assert response.success
    assert (tmp_path / "nested/result.txt").read_text() == "ok"
    assert response.ephemeral_output == "ephemeral plan"


def test_scripted_adapter_rejects_workspace_escape(tmp_path) -> None:
    adapter = ScriptedAdapter(
        (ScriptedAction(True, TokenUsage(0, 0), files={"../escape.txt": "no"}),)
    )
    with pytest.raises(ValueError, match="escape"):
        adapter.execute(task(), tmp_path, AdapterContext("run", 1))


def test_stdio_adapter_uses_json_stdin_and_parses_response(tmp_path) -> None:
    bridge = tmp_path / "bridge.py"
    bridge.write_text(
        "import json, sys\n"
        "d=json.load(sys.stdin)\n"
        "print(json.dumps({'success': True, 'input_tokens': 11, "
        "'output_tokens': 7, 'output': d['step_id']}))\n",
        encoding="utf-8",
    )
    config = StdioBridgeConfig(
        command=(sys.executable, str(bridge)),
        allowed_executable_names=frozenset({Path(sys.executable).name}),
    )
    response = StdioJsonAdapter(config).execute(task(), tmp_path, AdapterContext("run", 1))
    assert response.success
    assert response.usage == TokenUsage(11, 7)
    assert response.ephemeral_output == "edit"


def test_stdio_adapter_fails_closed_on_invalid_json(tmp_path) -> None:
    bridge = tmp_path / "bad_bridge.py"
    bridge.write_text("print('not-json')\n", encoding="utf-8")
    config = StdioBridgeConfig(
        command=(sys.executable, str(bridge)),
        allowed_executable_names=frozenset({Path(sys.executable).name}),
    )
    response = StdioJsonAdapter(config).execute(task(), tmp_path, AdapterContext("run", 1))
    assert not response.success
    assert response.error_code == "bridge_invalid_json"


def test_stdio_adapter_kills_bridge_at_output_limit(tmp_path) -> None:
    bridge = tmp_path / "loud_bridge.py"
    bridge.write_text("print('x' * 100000)\n", encoding="utf-8")
    config = StdioBridgeConfig(
        command=(sys.executable, str(bridge)),
        allowed_executable_names=frozenset({Path(sys.executable).name}),
        max_response_bytes=100,
    )
    response = StdioJsonAdapter(config).execute(task(), tmp_path, AdapterContext("run", 1))
    assert not response.success
    assert response.error_code == "bridge_output_limit"


def test_stdio_adapter_rejects_oversized_request_before_process_start(tmp_path) -> None:
    missing_bridge = tmp_path / "must_not_run.py"
    config = StdioBridgeConfig(
        command=(sys.executable, str(missing_bridge)),
        allowed_executable_names=frozenset({Path(sys.executable).name}),
        max_request_bytes=10,
    )
    response = StdioJsonAdapter(config).execute(task(), tmp_path, AdapterContext("run", 1))
    assert not response.success
    assert response.error_code == "bridge_request_limit"
