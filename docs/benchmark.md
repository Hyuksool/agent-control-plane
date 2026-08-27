# Benchmark Protocol

## Included offline benchmark

`agent-control-plane benchmark` runs the same three deterministic cases against:

1. `always_strong`: every eligible task uses the strong model fixture;
2. `policy_router`: low-risk work starts with the cheap fixture and escalates after validation failure; high-risk work goes directly to strong.

Cases:

- low-risk cheap success;
- low-risk cheap validation failure followed by strong success;
- high-risk direct strong routing.

Both strategies receive identical token usage and validation fixtures for each corresponding model attempt. Acceptance requires:

- no completion loss versus always-strong;
- lower total cost including failed attempts;
- zero policy-denied attempts in the valid fixture set.

This benchmark verifies orchestration logic only. It is not evidence that one real model equals another.

## Required real-provider study

A publishable evaluation should compare at least:

- one strong model alone;
- an Aider-like architect/editor workflow;
- a router plus an existing coding agent;
- this control plane using the same coding-agent bridge.

Use the same frozen task set, repository commit, environment image, dependency cache policy, hidden tests, time limit, and maximum spend.

Report per task and aggregate:

- hidden tests passed and task completion;
- lint/build/test exit status;
- wall time;
- every model attempt and escalation;
- input/output tokens;
- failed-attempt and total cost;
- policy violations and blocked actions;
- human intervention count;
- reproducibility across repeated runs.

## Anti-gaming rules

- Register tasks and acceptance tests before running models.
- Do not change prompts, tools, or time limits between arms except the declared routing policy.
- Count setup, retries, failures, and validator calls in cost and latency.
- Treat timeout, policy denial, and missing usage as failure or missing data; do not silently exclude them.
- Keep benchmark developers blinded to hidden tests where feasible.
- Publish task-level results and confidence intervals, not only averages.
- Label internal evaluations as internal and deterministic fixtures as fixtures.
- Do not use customer code or PHI without an approved data boundary.

## Proposed external gate

Before making a product savings claim, require all of the following on an external-team task set:

- completion non-inferiority margin defined prospectively;
- total cost reduction calculated with failures and retries;
- zero critical policy violations;
- reproducible results across at least two independent runs;
- raw task-level ledger available for audit without source or credential leakage.

Numerical commercial thresholds should be selected with the study owner and preregistered; they are intentionally not invented in this repository.
