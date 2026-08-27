# Agent Control Plane Implementation Plan

> **For Hermes:** Use subagent-driven-development discipline and verify every stage from live tool output.

**Goal:** Build a clean-room repository that combines provider routing, coding-agent execution, deterministic validation, bounded escalation, full retry cost accounting, team-specific aggregate learning, and privacy-safe observability.

**Architecture:** The orchestrator receives a task, decomposes it into typed steps, asks a deterministic policy router for an eligible model, executes through a provider adapter inside an explicit workspace boundary, runs structured validators, and escalates only when policy, cost, attempt, and wall-time budgets allow. Append-only traces store hashes and metrics rather than prompts, code, or raw output. Outcome learning adjusts future model scores using aggregate team/category statistics.

**Tech Stack:** Python 3.11+, stdlib runtime, pytest/ruff as development dependencies, TOML configuration, SQLite aggregate outcomes, JSONL traces.

---

## Acceptance criteria

1. Offline `demo` shows a cheap adapter failing validation, escalation to a stronger adapter, success, and total cost including both attempts.
2. Router rejects models that fail capability, risk, availability, policy, or remaining-budget gates and returns a machine-readable reason.
3. Executor never uses a shell, rejects workspace escape and forbidden commands, limits output, and enforces timeout.
4. Orchestrator has hard caps for attempts, total cost, and wall time; no retry loop can exceed them.
5. Validation uses explicit argv and exit codes. A failed validator cannot be treated as success.
6. Trace and outcome storage contain no prompt, source, raw command output, credential, or unhashed team identifier.
7. Benchmark compares always-strong and policy routing on the same deterministic cases and reports completion, quality, attempts, total cost, escalation, and policy violations.
8. Unit/integration/security tests and real CLI smoke all pass without network access.

## File plan

### Task 1 — Project contract and typed domain model
- Create `pyproject.toml`, `.gitignore`, `src/agent_control_plane/models.py`, package init.
- Tests: immutable models, Decimal cost, validation invariants.

### Task 2 — Provider registry and deterministic policy router
- Create `registry.py`, `router.py`.
- Tests: capability/risk/policy/budget gates, deterministic scoring and reasons.

### Task 3 — Fail-closed execution and validation
- Create `policy.py`, `executor.py`, `validation.py`.
- Tests: path escape, shell metacharacters, denied binaries, timeout, output cap, validator failure.

### Task 4 — Provider adapters and task decomposition
- Create `adapters/base.py`, `adapters/deterministic.py`, `adapters/stdio_json.py`, `decomposition.py`.
- Tests: JSON protocol, stdin transport, malformed output, heuristic typed steps.

### Task 5 — Cost accounting, privacy-safe trace, team learning
- Create `cost.py`, `trace.py`, `learning.py`.
- Tests: failures included in cost, budget checks, no body leakage, hashed team key, aggregate scoring.

### Task 6 — Bounded orchestration and escalation
- Create `orchestrator.py`.
- Tests: cheap→strong escalation, max attempts, max cost, wall-time stop, policy denial, terminal validation.

### Task 7 — CLI, deterministic benchmark, examples
- Create `cli.py`, `benchmark.py`, `examples/config.toml`, `examples/stdio_bridge.py`.
- Tests: CLI demo and benchmark subprocess smoke.

### Task 8 — Documentation and threat model
- Create `README.md`, `docs/architecture.md`, `docs/threat-model.md`, `docs/benchmark.md`.
- Explicitly distinguish existing open-source components from this repository's proposed contribution.

### Task 9 — Final verification and publication
- Run compile, pytest, ruff, demo, benchmark, secret scan, and diff review.
- Commit locally.
- Confirm final remote repository name, create private GitHub repository, push, and read back commit/default branch.
- Create source archive and verification report, mirror to Drive, verify remote size/MD5/parent/trashed state.
