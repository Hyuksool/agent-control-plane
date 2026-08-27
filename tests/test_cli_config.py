from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agent_control_plane.config import ConfigError, load_config


def run_cli(*args: str, input_text: str | None = None):
    return subprocess.run(
        [sys.executable, "-m", "agent_control_plane.cli", *args],
        input=input_text,
        capture_output=True,
        check=False,
        text=True,
    )


def test_cli_demo_proves_validation_escalation(tmp_path) -> None:
    result = run_cli("demo", "--workspace", str(tmp_path))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    report = payload["report"]
    assert report["status"] == "succeeded"
    assert [item["status"] for item in report["attempts"]] == [
        "validation_failed",
        "succeeded",
    ]
    assert report["total_cost_usd"] == "0.002700"


def test_cli_benchmark_beats_always_strong_without_completion_loss() -> None:
    result = run_cli("benchmark")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["acceptance"]["accepted"]
    assert payload["policy_router"]["completed"] == payload["baseline"]["completed"]
    assert float(payload["policy_router"]["total_cost_usd"]) < float(
        payload["baseline"]["total_cost_usd"]
    )


def test_configured_run_uses_stdio_bridge_and_keeps_task_out_of_trace(tmp_path) -> None:
    bridge = tmp_path / "bridge.py"
    bridge.write_text(
        "import json, pathlib, sys\n"
        "d=json.load(sys.stdin)\n"
        "if d['kind'] == 'edit': pathlib.Path(d['workspace'], 'result.txt').write_text('ok')\n"
        "print(json.dumps({'success': True, 'input_tokens': 10, 'output_tokens': 5, "
        "'output': d['kind']}))\n",
        encoding="utf-8",
    )
    (tmp_path / "check.py").write_text(
        "from pathlib import Path\n"
        "raise SystemExit(0 if Path('result.txt').read_text() == 'ok' else 1)\n",
        encoding="utf-8",
    )
    executable = Path(sys.executable).name
    config = tmp_path / "config.toml"
    config.write_text(
        f'''[run]
max_cost_usd = "1.00"
max_attempts_per_step = 1
max_wall_seconds = 10
edit_risk = "medium"
category = "test"

[execution]
allowed_executables = ["{executable}"]
max_timeout_seconds = 5
max_output_bytes = 100000

[[validation]]
argv = ["{sys.executable}", "check.py"]

[bridges.local]
command = ["{sys.executable}", "{bridge}"]
allowed_executable_names = ["{executable}"]
timeout_seconds = 5
max_response_bytes = 100000

[[models]]
provider = "local"
model = "bridge"
adapter = "local"
capabilities = ["plan", "edit", "review"]
max_risk = "high"
input_cost_per_1k = "0.001"
output_cost_per_1k = "0.002"
quality_prior = "0.90"
latency_ms = 10
''',
        encoding="utf-8",
    )
    parsed = load_config(config)
    assert parsed.models[0].profile.key == "local/bridge"

    secret_task = "private task body that must not enter the trace"
    result = run_cli(
        "run",
        "--config",
        str(config),
        "--workspace",
        str(tmp_path),
        "--team-id",
        "private-team",
        input_text=secret_task,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "succeeded"
    assert len(report["attempts"]) == 3
    raw_task_hash = hashlib.sha256(secret_task.encode("utf-8")).hexdigest()
    assert report["request_hash"] != raw_task_hash
    trace = (tmp_path / ".agent-control-plane/trace.jsonl").read_text(encoding="utf-8")
    assert secret_task not in trace
    assert raw_task_hash not in trace
    assert "private-team" not in trace
    key = tmp_path / ".agent-control-plane/team-hash.key"
    assert len(key.read_bytes()) == 32
    assert stat.S_IMODE(key.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('max_cost_usd = "0.10"', 'max_cost_usd = "NaN"'),
        ("max_wall_seconds = 30", "max_wall_seconds = inf"),
    ],
)
def test_config_rejects_non_finite_limits(tmp_path, old, new) -> None:
    example = Path(__file__).parents[1] / "examples/config.toml"
    config = tmp_path / "invalid.toml"
    config.write_text(
        example.read_text(encoding="utf-8").replace(old, new),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="invalid configuration"):
        load_config(config)
