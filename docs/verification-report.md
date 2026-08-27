# Verification Report

Generated: 2026-08-27 09:13:07 KST

## Scope

This report covers the local clean-room repository at the current uncommitted tree. It verifies the control-plane implementation and offline protocol; it does not claim real-provider quality, customer adoption, production sandboxing, or remote CI success.

## Implemented controls

- typed plan/edit/review decomposition;
- capability, risk, quality, cost, latency, provider/model, and team-history routing;
- stronger-model escalation after adapter or deterministic validation failure;
- failed-attempt and retry-inclusive task-level cost accounting;
- hard cost, attempt, timeout, output, and wall-time bounds;
- structured argv execution with `shell=False`;
- executable and Python-module allowlists;
- workspace path, network target, inline Python, and mutating Git denials;
- POSIX process-group termination after timeout or output-limit breach;
- protected validator/test integrity checks after every adapter attempt, including failed attempts;
- HMAC request/team identifiers, mode-0600 state files, aggregate-only outcome learning, and body-free allowlisted traces;
- stdin/stdout JSON bridge contract for separately reviewed coding-agent/provider wrappers;
- deterministic baseline benchmark and installable wheel.

## Verified results

| Gate | Result |
|---|---|
| Full pytest suite | 35 passed in 1.61 s |
| Ruff | All checks passed |
| Mypy | No issues in 22 source files |
| Bandit | 0 medium, 0 high; 5 low-confidence-safe subprocess findings |
| Compile | `src`, `tests`, and `examples` compiled |
| Git whitespace check | Passed |
| Wheel build | `agent_control_plane-0.1.0-py3-none-any.whl` built |
| Wheel SHA-256 | `d6d331e86a1ba91074b78e93ff5ec0ae0226d1c5a31511778492eaf63db56520` |
| Fresh-wheel demo | succeeded; 2 attempts |
| Deterministic benchmark | accepted |
| Policy-router benchmark cost | USD 0.054000 |
| Always-strong baseline cost | USD 0.075000 |
| Fresh-wheel stdio protocol | succeeded; 3 attempts |
| Persistent project files | 45 |
| Tracked text lines at initial commit | 3,876 |
| Python source files | 22 |
| Test files | 6 |

## Adversarial cases covered

- shell markers, unknown executables, network targets, inline Python, unapproved Python modules, workspace escape, and mutating Git are denied;
- stdout/stderr combined output overflow terminates the process;
- timeout terminates a spawned child process group on POSIX;
- symlinked protected validators are rejected;
- a failed adapter cannot hide validator/test tampering and trigger a retry;
- actual token usage over budget stops the run while retaining the failed cost;
- a single adapter call cannot exceed the run wall-time without a timed-out result;
- predictable task text is not exposed as a raw SHA-256 identifier;
- concurrent outcome writes retain all 80 test updates;
- task, raw team ID, model output, and command output bodies do not enter traces.

## Not yet verified

- real Aider, OpenHands, Claude Code Router, LiteLLM, or commercial-provider integration;
- quality or cost advantage on real coding tasks;
- container/microVM isolation and egress control;
- Linux CI on Python 3.11, 3.12, and 3.13 until GitHub publication;
- multi-team external validation, adoption, or willingness to pay;
- provider invoice reconciliation;
- signed policy/configuration workflow.

## Publication blocker

The code can be committed locally, but the private GitHub repository and final package/CLI rename require the user-approved repository name. The current `agent-control-plane` string is a descriptive local working name, not a proposed product brand.
