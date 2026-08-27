# Architecture

## Design goals

The control plane separates five concerns that are often coupled inside one coding agent:

1. planning and typed task decomposition;
2. model eligibility and routing;
3. agent execution through a reviewed adapter;
4. deterministic build/test/lint validation;
5. governance evidence: policy decisions, cost, outcomes, and traces.

This separation lets a team replace the coding agent or model provider without replacing its safety and evidence layer.

## Main flow

1. `TaskRequest` carries an in-memory instruction, workspace, team identifier, and hard budgets.
2. `HeuristicDecomposer` emits typed plan/edit/review steps. Another decomposer may be substituted.
3. `PolicyRouter` filters candidates by capability, risk ceiling, explicit provider/model policy, quality floor, exclusion after failure, and remaining budget.
4. Eligible candidates are scored deterministically using quality prior, aggregate team success, relative candidate cost, and latency.
5. A `ProviderAdapter` works in the workspace. The generic `StdioJsonAdapter` sends JSON through stdin to a pre-approved executable with `shell=False`.
6. `CommandValidator` verifies configured protected validator/test paths after every adapter
   attempt, then runs structured build/test/lint argv through `SafeExecutor`.
7. A failed adapter or validator excludes that model and raises the minimum quality floor. A retry occurs only if another eligible model remains and every hard budget permits it.
8. `CostLedger` records the actual reported tokens for every attempt, including failed attempts.
9. `OutcomeStore` updates aggregate counters keyed by an HMAC team hash. Request identifiers are
   also HMAC-derived so predictable task text cannot be checked against a raw digest. The store
   contains no prompt, source, response, or raw team ID.
10. `TraceWriter` appends only allowlisted hashes and metrics to a mode-0600 JSONL file.

## Hard invariants

- No model-generated command is executed implicitly.
- The validator never invokes a shell.
- Workspace escape is denied before process creation.
- A failure cannot be converted to success without a passing validator when validation is required.
- Actual usage can terminate a run even if preflight estimation passed.
- Failed attempts remain in total and failed-cost accounting.
- Attempts, cost, adapter timeout, validation timeout, output size, and total wall time are bounded.
- On POSIX, timeout/output enforcement kills the spawned process group so child processes do not
  outlive the bounded attempt.
- Configured protected validator/test files cannot be changed by either successful or failed
  adapter attempts without a fail-closed policy denial.
- Prompt and code may exist in process memory but are not serialized by reports, traces, or outcome learning.
- Ephemeral output passed between steps is truncated and never added to telemetry.

## Adapter protocol

Input JSON over stdin:

```json
{
  "run_id": "opaque-id",
  "attempt": 1,
  "step_id": "edit",
  "kind": "edit",
  "instruction": "in-memory task text",
  "workspace": "/absolute/reviewed/path",
  "previous_outputs": ["ephemeral prior-step output"],
  "previous_failure_code": null
}
```

Output JSON over stdout:

```json
{
  "success": true,
  "input_tokens": 1200,
  "output_tokens": 300,
  "output": "ephemeral summary for the next step",
  "error_code": null
}
```

The bridge may edit the workspace, but the control plane trusts success only after configured validation passes. Raw stdout is size-bounded and hashed; it is not written to trace.

## Limits of the current implementation

- `SafeExecutor` is not OS isolation.
- Pricing and quality priors are configuration inputs, not independently verified facts.
- Aggregate history is a deterministic routing input, not an online-learning guarantee.
- The included decomposer is heuristic; an LLM planner requires a reviewed bridge.
- No vendor-specific bridge is bundled because CLI contracts and licenses change independently.
