from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from agent_control_plane.executor import CommandSpec, SafeExecutor
from agent_control_plane.policy import ExecutionPolicy
from agent_control_plane.validation import CommandValidator


def policy(workspace: Path, *, output_limit: int = 1_000_000) -> ExecutionPolicy:
    return ExecutionPolicy(
        workspace_root=workspace,
        allowed_executables=frozenset({Path(sys.executable).name, "git"}),
        allowed_python_modules=frozenset({"pytest", "compileall"}),
        max_timeout_seconds=2,
        max_output_bytes=output_limit,
    )


def test_policy_denies_shell_network_inline_python_and_git_mutation(tmp_path) -> None:
    rules = policy(tmp_path)
    assert not rules.check(("curl", "https://example.com"), tmp_path, 1).allowed
    assert not rules.check((sys.executable, "-c", "print(1)"), tmp_path, 1).allowed
    assert not rules.check((sys.executable, "-m", "http.server"), tmp_path, 1).allowed
    assert rules.check((sys.executable, "-m", "compileall", "."), tmp_path, 1).allowed
    assert not rules.check((sys.executable, "ok.py;rm"), tmp_path, 1).allowed
    assert not rules.check(("git", "push"), tmp_path, 1).allowed


def test_policy_denies_cwd_and_argument_path_escape(tmp_path) -> None:
    rules = policy(tmp_path)
    assert not rules.check((sys.executable, "ok.py"), tmp_path.parent, 1).allowed
    decision = rules.check((sys.executable, "../outside.py"), tmp_path, 1)
    assert not decision.allowed
    assert decision.reason == "argument_path_outside_workspace"


def test_safe_executor_runs_argv_without_persisting_output(tmp_path) -> None:
    script = tmp_path / "ok.py"
    script.write_text("print('sensitive output')\n", encoding="utf-8")
    result = SafeExecutor(policy(tmp_path)).run(
        CommandSpec((sys.executable, "ok.py"), tmp_path, timeout_seconds=1)
    )
    assert result.exit_code == 0
    assert result.stdout_bytes > 0
    assert len(result.stdout_hash) == 64
    assert not hasattr(result, "stdout")


def test_executor_enforces_output_limit(tmp_path) -> None:
    script = tmp_path / "loud.py"
    script.write_text("print('x' * 100)\n", encoding="utf-8")
    result = SafeExecutor(policy(tmp_path, output_limit=10)).run(
        CommandSpec((sys.executable, "loud.py"), tmp_path, timeout_seconds=1)
    )
    assert result.policy_reason == "output_limit_exceeded"


def test_executor_enforces_timeout(tmp_path) -> None:
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(1)\n", encoding="utf-8")
    result = SafeExecutor(policy(tmp_path)).run(
        CommandSpec((sys.executable, "slow.py"), tmp_path, timeout_seconds=0.05)
    )
    assert result.timed_out
    assert result.exit_code == 124


def test_executor_timeout_kills_spawned_child_process(tmp_path) -> None:
    (tmp_path / "child.py").write_text(
        "import time\n"
        "from pathlib import Path\n"
        "time.sleep(0.2)\n"
        "Path('child-survived.txt').write_text('unsafe')\n",
        encoding="utf-8",
    )
    (tmp_path / "parent.py").write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, 'child.py'])\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )

    result = SafeExecutor(policy(tmp_path)).run(
        CommandSpec((sys.executable, "parent.py"), tmp_path, timeout_seconds=0.05)
    )
    time.sleep(0.3)

    assert result.timed_out
    assert not (tmp_path / "child-survived.txt").exists()


def test_validator_fails_on_nonzero_exit(tmp_path) -> None:
    script = tmp_path / "fail.py"
    script.write_text("raise SystemExit(7)\n", encoding="utf-8")
    validator = CommandValidator(SafeExecutor(policy(tmp_path)))
    summary = validator.validate(((sys.executable, "fail.py"),), tmp_path)
    assert not summary.success
    assert summary.checks[0].exit_code == 7


def test_validator_detects_protected_file_modification(tmp_path) -> None:
    protected = tmp_path / "validator.py"
    protected.write_text("raise SystemExit(7)\n", encoding="utf-8")
    validator = CommandValidator(
        SafeExecutor(policy(tmp_path)),
        protected_paths=("validator.py",),
    )
    snapshot = validator.snapshot_integrity(tmp_path)
    protected.write_text("raise SystemExit(0)\n", encoding="utf-8")

    summary = validator.validate((), tmp_path, integrity_snapshot=snapshot)

    assert not summary.success
    assert summary.checks[0].policy_reason == "protected_path_modified"


def test_validator_rejects_symlinked_protected_path(tmp_path) -> None:
    target = tmp_path / "target.py"
    target.write_text("raise SystemExit(7)\n", encoding="utf-8")
    (tmp_path / "validator.py").symlink_to(target)
    validator = CommandValidator(
        SafeExecutor(policy(tmp_path)),
        protected_paths=("validator.py",),
    )

    with pytest.raises(ValueError, match="symlink"):
        validator.snapshot_integrity(tmp_path)
