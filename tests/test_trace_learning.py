from __future__ import annotations

import hashlib
import json
import stat
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from agent_control_plane.learning import OutcomeStore
from agent_control_plane.trace import TraceWriter


def test_trace_is_allowlisted_private_and_body_free(tmp_path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = TraceWriter(path)
    writer.emit(
        "run_started",
        run_id="run-1",
        request_hash="a" * 64,
        team_hash="b" * 64,
        category="coding",
    )
    line = json.loads(path.read_text(encoding="utf-8"))
    assert line["run_id"] == "run-1"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(ValueError, match="not allowed"):
        writer.emit("run_started", prompt="secret source body")
    assert "secret source body" not in path.read_text(encoding="utf-8")


def test_outcome_store_hashes_team_and_aggregates_only(tmp_path) -> None:
    path = tmp_path / "outcomes.sqlite3"
    store = OutcomeStore(path, team_hash_key=b"0123456789abcdef0123456789abcdef")
    store.record(
        "real-team-name",
        "coding",
        "provider/model",
        succeeded=False,
        cost_usd=Decimal("0.10"),
    )
    store.record(
        "real-team-name",
        "coding",
        "provider/model",
        succeeded=True,
        cost_usd=Decimal("0.20"),
    )
    stats = store.stats("real-team-name", "coding", "provider/model")
    assert stats.attempts == 2
    assert stats.successes == 1
    assert stats.total_cost_usd == Decimal("0.30")
    assert store.team_hash("real-team-name") != "real-team-name"
    assert store.request_hash("predictable task") != hashlib.sha256(
        b"predictable task"
    ).hexdigest()
    assert b"real-team-name" not in path.read_bytes()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_outcome_store_does_not_lose_concurrent_updates(tmp_path) -> None:
    store = OutcomeStore(
        tmp_path / "outcomes.sqlite3",
        team_hash_key=b"0123456789abcdef0123456789abcdef",
    )

    def record_batch(_: int) -> None:
        for _ in range(20):
            store.record(
                "team",
                "coding",
                "provider/model",
                succeeded=True,
                cost_usd=Decimal("0.01"),
            )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(record_batch, range(4)))

    stats = store.stats("team", "coding", "provider/model")
    assert stats.attempts == 80
    assert stats.successes == 80
    assert stats.total_cost_usd == Decimal("0.80")
