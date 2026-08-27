from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from decimal import Decimal
from pathlib import Path

from .models import TeamStats


class OutcomeStore:
    def __init__(self, path: Path, *, team_hash_key: bytes) -> None:
        if not path.is_absolute():
            raise ValueError("outcome database path must be absolute")
        if len(team_hash_key) < 16:
            raise ValueError("team_hash_key must contain at least 16 bytes")
        self.path = path
        self.team_hash_key = team_hash_key
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS aggregate_outcomes (
                    team_hash TEXT NOT NULL,
                    category TEXT NOT NULL,
                    model_key TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    successes INTEGER NOT NULL DEFAULT 0,
                    total_cost_usd TEXT NOT NULL DEFAULT '0',
                    PRIMARY KEY (team_hash, category, model_key)
                )
                """
            )

    def team_hash(self, team_id: str) -> str:
        if not team_id:
            raise ValueError("team_id must not be empty")
        return self._private_hash("team", team_id)

    def request_hash(self, instruction: str) -> str:
        if not instruction:
            raise ValueError("instruction must not be empty")
        return self._private_hash("request", instruction)

    def _private_hash(self, namespace: str, value: str) -> str:
        return hmac.new(
            self.team_hash_key,
            f"{namespace}\x00{value}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def record(
        self,
        team_id: str,
        category: str,
        model_key: str,
        *,
        succeeded: bool,
        cost_usd: Decimal,
    ) -> None:
        key = self.team_hash(team_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT attempts, successes, total_cost_usd
                FROM aggregate_outcomes
                WHERE team_hash = ? AND category = ? AND model_key = ?
                """,
                (key, category, model_key),
            ).fetchone()
            if row is None:
                attempts = 1
                successes = int(succeeded)
                total_cost = cost_usd
            else:
                attempts = int(row[0]) + 1
                successes = int(row[1]) + int(succeeded)
                total_cost = Decimal(str(row[2])) + cost_usd
            connection.execute(
                """
                INSERT INTO aggregate_outcomes
                    (team_hash, category, model_key, attempts, successes, total_cost_usd)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_hash, category, model_key) DO UPDATE SET
                    attempts = excluded.attempts,
                    successes = excluded.successes,
                    total_cost_usd = excluded.total_cost_usd
                """,
                (key, category, model_key, attempts, successes, str(total_cost)),
            )

    def stats(self, team_id: str, category: str, model_key: str) -> TeamStats:
        key = self.team_hash(team_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT attempts, successes, total_cost_usd
                FROM aggregate_outcomes
                WHERE team_hash = ? AND category = ? AND model_key = ?
                """,
                (key, category, model_key),
            ).fetchone()
        if row is None:
            return TeamStats()
        return TeamStats(int(row[0]), int(row[1]), Decimal(str(row[2])))
